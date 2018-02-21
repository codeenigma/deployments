from fabric.api import *
from fabric.operations import put
from fabric.contrib.files import *
import random
import string
# Custom Code Enigma modules
import common.Utils
import common.MySQL


# Generate a drush alias for this site
@task
@roles('app_all')
def generate_drush_alias(repo, url, branch, alias):
  print "===> Generating Drush alias"
  # Make sure drush directory exists
  sudo("mkdir -p /etc/drush")
  # Make sure the alias file exists
  sudo("touch /etc/drush/%s_%s.alias.drushrc.php" % (alias, branch))

  # Append the necessary include and other settings
  append_string = """<?php

$aliases['%s_%s'] = array(
  'root' => '/var/www/live.%s.%s/www',
  'uri' => '%s',
);""" % (alias, branch, repo, branch, url)
  append("/etc/drush/%s_%s.alias.drushrc.php" % (alias, branch), append_string, use_sudo=True)


@task
@roles('app_all')
def initial_build_create_live_symlink(repo, branch, build):
  print "===> Setting the live document root symlink"
  # We need to force this to avoid a repeat of https://redmine.codeenigma.net/issues/20779
  sudo("ln -nsf /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))

# If composer was run beforehand because the site is Drupal 8, it will have created a
# files directory for the site with 777 perms. Move it aside and fix perms.
@task
@roles('app_all')
def initial_build_create_files_symlink(repo, branch, build, site, alias):
  with settings(warn_only=True):
    if run("stat /var/www/%s_%s_%s/www/sites/%s/files" % (repo, branch, build, site)).return_code == 0:
      print "===> Found a files directory, probably Drupal 8, making it safe"
      sudo("mv /var/www/%s_%s_%s/www/sites/%s/files /var/www/%s_%s_%s/www/sites/%s/files_bak" % (repo, branch, build, site, repo, branch, build, site))
      sudo("chmod 775 /var/www/%s_%s_%s/www/sites/%s/files_bak" % (repo, branch, build, site))
      sudo("find /var/www/%s_%s_%s/www/sites/%s/files_bak -type d -print0 | xargs -r -0 chmod 775" % (repo, branch, build, site))
      sudo("find /var/www/%s_%s_%s/www/sites/%s/files_bak -type f -print0 | xargs -r -0 chmod 664" % (repo, branch, build, site))
      sudo("mv /var/www/%s_%s_%s/www/sites/%s/files_bak/* /var/www/shared/%s_%s_files/" % (repo, branch, build, site, alias, branch))
  print "===> Creating files symlink"
  sudo("ln -s /var/www/shared/%s_%s_files /var/www/%s_%s_%s/www/sites/%s/files" % (alias, branch, repo, branch, build, site))


# Run database updates, just in case. Separate function to the main Drupal one
# as we cannot revert database or settings.php during an initial build.
@task
@roles('app_primary')
def initial_build_updatedb(repo, branch, build, site, drupal_version):
  print "===> Running any database hook updates"
  with settings(warn_only=True):
    if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y updatedb'" % (repo, branch, build, site)).failed:
      raise SystemExit("Could not apply database updates! Everything else has been done, but failing the build to alert to the fact database updates could not be run.")
    if drupal_version == '8':
      if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y entity-updates'" % (repo, branch, build, site)).failed:
        print "Could not carry out entity updates! Continuing anyway, as this probably isn't a major issue."
  print "===> Database updates applied"


# Function used by Drupal 8 builds to import site config
@task
@roles('app_primary')
def initial_build_config_import(repo, branch, build, site, drupal_version):
  with settings(warn_only=True):
    # Check to see if this is a Drupal 8 build
    if drupal_version == '8':
      print "===> Importing configuration for Drupal 8 site..."
      if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y cim'" % (repo, branch, build, site)).failed:
        raise SystemExit("Could not import configuration! Failing the initial build.")
      else:
        print "===> Configuration imported."


# Stuff to do when this is the initial build
@task
@roles('app_primary')
def initial_build(repo, url, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster=False, rds=False):
  print "===> This looks like the first build! We have some things to do.."

  print "===> Making the shared files dir and setting symlink"
  sudo("mkdir -p /var/www/shared/%s_%s_files" % (alias, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s_files" % (alias, branch))
  sudo("chmod 775 /var/www/shared/%s_%s_files" % (alias, branch))

  print "===> Making the private files dir"
  sudo("mkdir -p /var/www/shared/%s_%s_private_files" % (alias, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s_private_files" % (alias, branch))
  sudo("chmod 775 /var/www/shared/%s_%s_private_files" % (alias, branch))

  print "===> Preparing the database"

  # This process creates a database, database user/pass, imports the db dump from the repo
  # and generates the settings.php database credential string via a drush site-install.

  # Check if a db/ directory exists first.
  db_dir = False
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s -maxdepth 1 -type d -name db | egrep '.*'" % (repo, branch, build)).return_code == 0:
      db_dir = True

  # We can default these to None, mysql_new_database() will sort itself out
  list_of_app_servers = None
  db_host = None

  # For clusters we need to do some extra things
  if cluster:
    # This is the Database host that we need to insert into Drupal settings.php. It is different from the main db host because it might be a floating IP
    db_host = config.get('DrupalDBHost', 'dbhost')
    # Convert a list of apps back into a string, to pass to the MySQL new database function for setting appropriate GRANTs to the database
    list_of_app_servers = env.roledefs['app_all']

  if cluster and config.has_section('AppIPs'):
    list_of_app_servers = env.roledefs['app_ip_all']

  # If this is a feature branch build, we want to pass in the branch name as buildtype, when
  # create a new database. This is so there is some difference in db name between feature branch
  # builds.
  preserve_buildtype = buildtype
  if buildtype == "custombranch":
    buildtype = branch

  # Prepare the database
  # We'll get back db_name, db_username, db_password and db_host from this call as a list in new_database
  new_database = common.MySQL.mysql_new_database(alias, buildtype, rds, db_name, db_host, db_username, mysql_version, db_password, mysql_config, list_of_app_servers)

  # Set the buildtype back to the original buildtype
  buildtype = preserve_buildtype

  # Now install Drupal
  site_root = "/var/www/%s_%s_%s/www" % (repo, branch, build)

  # We need to actually run a drush si first, then drop the tables and import
  # the database in the db/ directory.
  with cd("%s/sites/%s" % (site_root, site)):
    run("cp default.settings.php settings.php")
    db_url = "mysql://%s:%s@%s/%s" % (new_database[1], new_database[2], new_database[3], new_database[0])
    print "===> Installing Drupal with MySQL string of %s" % db_url
    run ("drush si %s -y --db-url=%s" % (profile, db_url))
    # Append the necessary include and other settings
    append_string = """$config_directories['sync'] = '../config/sync';
$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include_once($file);
}""" % (repo, branch, build, site, buildtype)
    append("settings.php", append_string, use_sudo=True)

  # Now if we have a database to import we can do that
  if db_dir and dump_file:
    with cd("%s/sites/%s" % (site_root, site)):
      sudo("drush -y sql-drop")
      site_root = "/var/www/%s_%s_%s" % (repo, branch, build)
      common.MySQL.mysql_import_dump(site_root, new_database[0], dump_file, new_database[3], rds, mysql_config)
      site_root = "/var/www/%s_%s_%s/www" % (repo, branch, build)
  else:
    print "===> No database found to seed from, moving on."

  # This sanitisation bit normally only occurs during the initial deployment of a custom branch
  # which allows the user to select which database to use. They can choose whether it is santised
  # or not.
  if buildtype == "custombranch" and sanitise == "yes":
    print "===> Sanitising database..."
    if sanitised_password is None:
      sanitised_password = common.Utils._gen_passwd()
    if sanitised_email is None:
      sanitised_email = 'example.com'
    with cd("%s/sites/%s" % (site_root, site)):
      with settings(warn_only=True):
        if run("drush -y sql-sanitize --sanitize-email=%s+%%uid@%s --sanitize-password=%s" % (alias, sanitised_email, sanitised_password)).failed:
          print "Could not sanitise database. Aborting this build."
          raise SystemError("Could not sanitise database. Aborting this build.")
        else:
          print "===> Data sanitised, email domain set to %s+%%uid@%s, passwords set to %s" % (alias, sanitised_email, sanitised_password)
          print "Sanitised database."

  print "===> Correcting files directory permissions and ownership..."
  sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_files" % (alias, branch))
  sudo("chmod 775 /var/www/shared/%s_%s_files" % (alias, branch))

  print "===> Temporarily moving settings.php to shared area /var/www/shared/%s_%s.settings.inc so all servers in a cluster can access it" % (alias, branch)
  sudo("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/shared/%s_%s.settings.inc" % (repo, branch, build, site, alias, branch))


@task
@roles('app_all')
def initial_build_move_settings(alias, branch):
  # Prepare the settings.inc file after installation
  print "===> Copying %s_%s.settings.inc from shared to config area /var/www/config/%s_%s.settings.inc. Do an 'include' of this in your main settings.php, or else it will be symlinked directly as settings.php" % (alias, branch, alias, branch)
  # Try and make a config directory, just in case
  if sudo("mkdir -p /var/www/config").failed:
    raise SystemExit("Could not create shared config directory")
  sudo("cp /var/www/shared/%s_%s.settings.inc /var/www/config/%s_%s.settings.inc" % (alias, branch, alias, branch))
  sudo("chown jenkins:www-data /var/www/config/%s_%s.settings.inc" % (alias, branch))
  sudo("chmod 644 /var/www/config/%s_%s.settings.inc" % (alias, branch))


# Copy the dummy vhost and change values.
@task
@roles('app_all')
def initial_build_vhost(repo, url, branch, build, alias, buildtype, ssl_enabled, ssl_cert, ssl_ip, httpauth_pass, drupal_common_config, webserverport):
  # Some quick clean-up from earlier, delete the 'shared' settings.inc
  with settings(warn_only=True):
    if run("stat /var/www/shared/%s_%s.settings.inc" % (alias, branch)).return_code == 0:
      sudo("rm /var/www/shared/%s_%s.settings.inc" % (alias, branch))
      print "===> Deleting /var/www/shared/%s_%s.settings.inc as we don't need it now" % (alias, branch)
  # Work out whether we are running Apache or Nginx (compensating for RedHat which uses httpd as name)
  # Assume Nginx by default
  webserver = "nginx"
  with settings(hide('running', 'warnings', 'stdout', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd']
    for service in services:
      if run('pgrep -lf %s | egrep -v "bash|grep" > /dev/null' % service).return_code == 0:
        webserver = service

  print "===> Setting up an %s vhost" % webserver
  # Abort if the vhost already exists - something strange has happened here,
  # perhaps we shouldn't have been doing a fresh install at all
  with settings(warn_only=True):
    if run("stat /etc/%s/sites-available/%s.conf" % (webserver, url)).return_code == 0:
      raise SystemError("The VirtualHost config file /etc/%s/sites-available/%s.conf already existed! Aborting." % (webserver, url))

  # Copy webserver dummy vhosts to server
  print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/vhosts/%s/*' % webserver, '/etc/%s/sites-available' % webserver, mode=0644, use_sudo=True).failed:
    raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
  else:
    print "===> Dummy vhosts copied to app server(s)."

  # If this site is being deployed from a custom branch job, we need to establish which dummy
  # vhost to use. If the ssl_enabled option is set in the config.ini file, use the
  # dummy_feature_branch_ssl.conf vhost. If it is not yet, we can use the
  # dummy_feature_branch.conf vhost.
  if buildtype == "custombranch":
    # Currently, this only works when the webserver in question is nginx.
    # TODO: make this work with nginx *and* apache
    if webserver == "nginx":
      if ssl_enabled:
        if ssl_cert is None:
          # If ssl_enabled is True in config.ini, ssl_cert MUST contain the name of the ssl cert
          # and key to be used, otherwise the job will fail.
          print "What? SSL is enabled for this feature branch build, but the SSL file name hasn't been passed. We cannot proceed. Abort build."
          raise SystemError("What? SSL is enabled for this feature branch build, but the SSL file name hasn't been passed. We cannot proceed. Abort build.")
        else:
          # Set which dummy vhost file to use.
          dummy_file = 'dummy_feature_branch_ssl.conf'
          with settings(warn_only=True):
            # Check that the ssl_cert files exist. If they don't, revert to using wildcard.codeenigma.net.
            # Check that those files exist, too. If they don't, abort the build, as there aren't
            # any certificates/keys to use.
            print "===> Checking that %s certificate and key exists..." % ssl_cert
            if run("stat /etc/%s/ssl/%s.crt" % (webserver, ssl_cert)).failed or run("stat /etc/%s/ssl/%s.key" % (webserver, ssl_cert)).failed:
              print "Could not find a crt or key for %s. Let's search for wildcard.codeenigma.net instead." % ssl_cert
              if run("stat /etc/%s/ssl/wildcard.codeenigma.net.crt" % (webserver, ssl_cert)).failed:
                print "Could not find /etc/%s/ssl/wildcard.codeenigma.net.crt either. Aborting build, as there are no SSL certificates to use." % webserver
                raise SystemError("Could not find /etc/%s/ssl/wildcard.codeenigma.net.crt either. Aborting build, as there are no SSL certificates to use." % webserver)
              else:
                print "Found wildcard.codeenigma.net. We'll use that as the SSL certificate, even though there may be some SSL errors."
                ssl_cert = "wildcard.codeenigma.net"
            else:
              print "Found an SSL cert and key for %s. Continuing with the build..." % ssl_cert
      else:
        # If ssl_enabled is False, just use a the default feature branch vhost.
        dummy_file = 'dummy_feature_branch.conf'
    else:
      dummy_file = 'dummy.conf'

    sudo("cp /etc/%s/sites-available/%s /etc/%s/sites-available/%s.conf" % (webserver, dummy_file, webserver, url))

    # If httpauth_pass is None, then we won't check for a .htpasswd file, but if it is set, then
    # we will chheck if there's a .htpasswd file in /etc/[nginx|apache2]/passwords/repo.custombranch.htpasswd
    # If there is, we'll use that to put the site behind HTTP auth. If not, we'll create a
    # the file with a random password
    if httpauth_pass is not None:
      common.Utils.create_httpauth(webserver, repo, branch, url, httpauth_pass)

    if ssl_enabled:
      sudo("sed -i s/sslcert/%s/g /etc/%s/sites-available/%s.conf" % (ssl_cert, webserver, url))

      ssl_replace = ssl_ip if ssl_ip is not None else ""
      sudo("sed -i s/sslip/%s/g /etc/%s/sites-available/%s.conf" % (ssl_replace, webserver, url))


    if drupal_common_config is not None and webserver == "nginx":
      with settings(warn_only=True):
        if run("stat /etc/nginx/conf.d/%s" % drupal_common_config).failed:
          print "Could not find the config file /etc/nginx/conf.d/%s. Reverting to the default config." % drupal_common_config
          drupal_common_config = "drupal_common_config"
        else:
          sudo("sed -i s/drupal_common_config/%s/g /etc/nginx/sites-available/%s.conf" % (drupal_common_config, url))

  else:
    sudo("cp /etc/%s/sites-available/dummy.conf /etc/%s/sites-available/%s.conf" % (webserver, webserver, url))

  sudo("sed -i s/dummyfqdn/%s/g /etc/%s/sites-available/%s.conf" % (url, webserver, url))
  sudo("sed -i s/dummyport/%s/g /etc/%s/sites-available/%s.conf" % (webserverport, webserver, url))
  sudo("sed -i s/dummy/%s.%s/g /etc/%s/sites-available/%s.conf" % (repo, branch, webserver, url))
  sudo("ln -s /etc/%s/sites-available/%s.conf /etc/%s/sites-enabled/%s.conf" % (webserver, url, webserver, url))
  print "Tidy up and remove the dummy vhosts. Don't fail the build if they can't be removed."
  with settings(warn_only=True):
    sudo("rm /etc/%s/sites-available/dummy*.conf" % webserver)

  url_output = url.lower()
  print "***** Your URL is http://%s *****" % url_output
  # @TODO push this vhost back into puppet. See RS 14081
  # Clone a copy of the puppet repo locally
  #local("git clone git@git.codeenigma.com:ce-ops/puppet-enigma.git /tmp/puppet_for_%s" % build)
  # Fetch the new vhost from the server
  #get("/etc/%s/sites-available/%s.conf" % (webserver, url), "/tmp/puppet_for_%s/modules/%s/files/vhosts/%s.conf" % (build, webserver, url))
  # Need the node name
  #fqdn = run("hostname -f")
  # @TODO this is probably not a fool-proof way of inserting into the second last line of the node .pp file....  (e.g if last line is whitespace, we're doomed)
  #local("sed -i '$i\ \ '%s::vhost\ {\ \'%s\':\ } /tmp/puppet_for_%s/manifests/%s.pp" % (webserver, url, build, fqdn))
  # Add the changes back into Git and push
  #local("cd /tmp/puppet_for_%s && git add -f . && git commit -m 'Added %s.conf vhost'")
  #local("cd /tmp/puppet_for_%s && git-jenkins-push -i /var/lib/jenkins/.ssh/id_rsa_gitlab_push push origin master" % build)


