from fabric.api import *
from fabric.operations import put
from fabric.contrib.files import *
import random
import string
# Custom Code Enigma modules
import common.Utils


# Generate a drush alias for this site
@task
@roles('app_all')
def generate_drush_alias(repo, url, branch):
  print "===> Generating Drush alias"
  # Copy drush script to server(s)
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/drush_alias.sh', '/home/jenkins', mode=0755).failed:
    raise SystemExit("Could not copy the drush script to the application server, aborting because we won't be able to make a drush alias")
  else:
    print "===> Drush alias preparation script copied to %s:/home/jenkins/drush_alias.sh" % env.host
  sudo("/home/jenkins/drush_alias.sh %s %s %s" % (repo, url, branch))


@task
@roles('app_all')
def initial_build_create_live_symlink(repo, branch, build):
  print "===> Setting the live document root symlink"
  # We need to force this to avoid a repeat of https://redmine.codeenigma.net/issues/20779
  sudo("ln -nsf /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))

# If composer was run beforehand because the site is Drupal 8, it'll have created a sites/default/files directory with 777 perms. Move it aside and fix perms.
@task
@roles('app_all')
def initial_build_create_files_symlink(repo, branch, build):
  with settings(warn_only=True):
    if run("stat /var/www/%s_%s_%s/www/sites/default/files" % (repo, branch, build)).return_code == 0:
      print "===> Found a files directory, probably Drupal 8, making it safe"
      sudo("mv /var/www/%s_%s_%s/www/sites/default/files /var/www/%s_%s_%s/www/sites/default/files_bak" % (repo, branch, build, repo, branch, build))
      sudo("chmod 775 /var/www/%s_%s_%s/www/sites/default/files_bak" % (repo, branch, build))
      sudo("find /var/www/%s_%s_%s/www/sites/default/files_bak -type d -print0 | xargs -r -0 chmod 775" % (repo, branch, build))
      sudo("find /var/www/%s_%s_%s/www/sites/default/files_bak -type f -print0 | xargs -r -0 chmod 664" % (repo, branch, build))
      sudo("mv /var/www/%s_%s_%s/www/sites/default/files_bak/* /var/www/shared/%s_%s_files/" % (repo, branch, build, repo, branch))
  print "===> Creating files symlink"
  sudo("ln -s /var/www/shared/%s_%s_files /var/www/%s_%s_%s/www/sites/default/files" % (repo, branch, repo, branch, build))

# Stuff to do when this is the initial build
@task
@roles('app_primary')
def initial_build(repo, url, branch, build, profile, buildtype, sanitise, config, drupal_version, sanitised_password, sanitised_email, cluster=False, rds=False):
  print "===> This looks like the first build! We have some things to do.."

  drupal8 = False

  print "===> Making the shared files dir and setting symlink"
  sudo("mkdir -p /var/www/shared/%s_%s_files" % (repo, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s_files" % (repo, branch))
  sudo("chmod 775 /var/www/shared/%s_%s_files" % (repo, branch))

  print "===> Making the private files dir"
  sudo("mkdir -p /var/www/shared/%s_%s_private_files" % (repo, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s_private_files" % (repo, branch))
  sudo("chmod 775 /var/www/shared/%s_%s_private_files" % (repo, branch))

  print "===> Preparing the database"
  # this process creates a database, database user/pass, imports the db dump from the repo
  # and generates the settings.php database credential string. It's capable of working out
  # whether the site is Drupal 6 or Drupal 7 and adjust its database string format appropriately.
  newpass = common.Utils._gen_passwd()
  #if(glob.glob("/var/www/%s_%s_%s/db/*.sql.bz2")):

  # Check if a db/ directory exists first.
  db_dir = False
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s -maxdepth 1 -type d -name db | egrep '.*'" % (repo, branch, build)).return_code == 0:
      db_dir = True

  # Select the correct db script to use
  dbscript = ""
  if drupal_version == '8':
    if cluster:
      dbscript = "mysqlpreparenoimport_remote"
      if rds:
        dbscript = "mysqlpreparenoimport_rds"
    else:
      dbscript = "mysqlpreparenoimport"
  else:
    if db_dir:
      if cluster:
        dbscript = "mysqlprepare_remote"
      else:
        dbscript = "mysqlprepare"
    else:
      if cluster:
        dbscript = "mysqlpreparenoimport_remote"
      else:
        dbscript = "mysqlpreparenoimport"


  print "===> Will use the script %s.sh for preparing the database" % dbscript

  # Copy database script to server(s)
  script_dir = os.path.dirname(os.path.realpath(__file__))
  path_to_local_script = script_dir + '/../util/' + dbscript + '.sh'
  if put(path_to_local_script, '/home/jenkins', mode=0755).failed:
    raise SystemExit("Could not copy the database script to the application server, aborting because we won't be able to make a database")
  else:
    print "===> Database preparation script %s.sh copied to %s:/home/jenkins/%s.sh" % (dbscript, env.host, dbscript)

  # For clusters we need to do some extra things
  app_ip_override = False
  if cluster:
    # This is the Database host that we need to insert into Drupal settings.php. It is different from the main db host because it might be a floating IP
    dbhost = config.get('DrupalDBHost', 'dbhost')
    # Convert a list of apps back into a string, to pass to the mysqlprepare script for setting appropriate GRANTs to the database
    apps_list = ",".join(env.roledefs['app_all'])

    if config.has_section('AppIPs'):
      app_ip_override = True
      apps_ip_list = ",".join(env.roledefs['app_ip_all'])

  if app_ip_override:
    list_of_app_servers = apps_ip_list
  else:
    list_of_app_servers = env.host

  # Prepare the database
  if db_dir:
    if drupal_version == '8':
      drupal8 = True
      # We need to actually run a drush si first with Drupal 8. Something to do with hash salts.
      # So, first run a mysqlpreparenoimport.sh, then drop the tables and import the database in
      # the db/ directory.
      sitedir = "/var/www/%s_%s_%s/www" % (repo, branch, build)
      if cluster:
        common.Utils._sshagent_run("/home/jenkins/%s.sh %s %s %s %s %s %s %s %s" % (dbscript, dbhost, repo, newpass, sitedir, branch, profile, list_of_app_servers, drupal8))
      else:
        sudo("/home/jenkins/%s.sh %s %s %s %s %s %s" % (dbscript, repo, newpass, sitedir, buildtype, profile, drupal8))
      with cd("%s/sites/default" % sitedir):
        sudo("drush -y sql-drop")
        if sudo("bzcat /var/www/%s_%s_%s/db/*.sql.bz2 | drush -y sql-cli" % (repo, branch, build)).failed:
          print "Could not import database. Aborting build."
          raise SystemError("Could not import database. Aborting build.")
    else:
      sudo("bunzip2 /var/www/%s_%s_%s/db/*.sql.bz2" % (repo, branch, build))
      sitedir = "/var/www/%s_%s_%s/www" % (repo, branch, build)
      if cluster:
        common.Utils._sshagent_run("/home/jenkins/%s.sh %s %s %s %s %s /var/www/%s_%s_%s/db %s" % (dbscript, dbhost, repo, newpass, sitedir, branch, repo, branch, build, list_of_app_servers))
      else:
        # mysqlprepare.sh <databasename> <databasepass> <site_root> <branch> <dumpfile>
        sudo("/home/jenkins/%s.sh %s %s /var/www/live.%s.%s %s $(find /var/www/%s_%s_%s/db -type f -name *.sql)" % (dbscript, repo, newpass, repo, branch, buildtype, repo, branch, build))
  else:
    sitedir = "/var/www/%s_%s_%s/www" % (repo, branch, build)
    if drupal_version == '8':
      drupal8 = True
      if cluster:
        common.Utils._sshagent_run("/home/jenkins/%s.sh %s %s %s %s %s %s %s %s" % (dbscript, dbhost, repo, newpass, sitedir, branch, profile, list_of_app_servers, drupal8))
      else:
        sudo("/home/jenkins/%s.sh %s %s %s %s %s %s" % (dbscript, repo, newpass, sitedir, buildtype, profile, drupal8))
    else:
      if cluster:
        common.Utils._sshagent_run("/home/jenkins/%s.sh %s %s %s %s %s %s %s" % (dbscript, dbhost, repo, newpass, sitedir, branch, profile, list_of_app_servers))
      else:
        sudo("/home/jenkins/%s.sh %s %s %s %s %s" % (dbscript, repo, newpass, sitedir, buildtype, profile))

  # This sanitisation bit normally only occurs during the initial deployment of a custom branch
  # which allows the user to select which database to use. They can choose whether it is santised
  # or not.
  if buildtype == "custombranch" and sanitise == "yes":
    print "===> Sanitising database..."
    if sanitised_password is None:
      sanitised_password = common.Utils._gen_passwd()
    if sanitised_email is None:
      sanitised_email = 'example.com'
    with cd("%s/sites/default" % sitedir):
      with settings(warn_only=True):
        if run("drush -y sql-sanitize --sanitize-email=%s+%%uid@%s --sanitize-password=%s" % (repo, sanitised_email, sanitised_password)).failed:
          print "Could not sanitise database. Aborting this build."
          raise SystemError("Could not sanitise database. Aborting this build.")
        else:
          print "===> Data sanitised, email domain set to %s, passwords set to %s" % (sanitised_email, sanitised_password)
          print "Sanitised database."

  if drupal_version == '8':
    # If the site is Drupal 8, after the initial build, the config directory will have incorrect permissions, which is not ideal.
    print "===> Correcting config directory permissions and ownership..."
    sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_files" % (repo, branch))
    sudo("chmod 775 /var/www/shared/%s_%s_files" % (repo, branch))

  print "===> Temporarily moving settings.php to shared area /var/www/shared/%s_%s.settings.inc so all servers in a cluster can access it" % (repo, branch)
  sudo("mv /var/www/%s_%s_%s/www/sites/default/settings.php /var/www/shared/%s_%s.settings.inc" % (repo, branch, build, repo, branch))


@task
@roles('app_all')
def initial_build_move_settings(repo, branch):
  # Prepare the settings.inc file after installation
  print "===> Copying %s_%s.settings.inc from shared to config area /var/www/config/%s_%s.settings.inc. Do an 'include' of this in your main settings.php, or else it will be symlinked directly as settings.php" % (repo, branch, repo, branch)
  sudo("cp /var/www/shared/%s_%s.settings.inc /var/www/config/%s_%s.settings.inc" % (repo, branch, repo, branch))
  sudo("chown jenkins:www-data /var/www/config/%s_%s.settings.inc" % (repo, branch))
  sudo("chmod 644 /var/www/config/%s_%s.settings.inc" % (repo, branch))


# Copy the dummy vhost and change values.
@task
@roles('app_all')
def initial_build_vhost(repo, url, branch, build, buildtype, ssl_enabled, ssl_cert, ssl_ip, httpauth_pass, drupal_common_config, webserverport):
  # Some quick clean-up from earlier, delete the 'shared' settings.inc
  with settings(warn_only=True):
    if run("stat /var/www/shared/%s_%s.settings.inc" % (repo, branch)).return_code == 0:
      sudo("rm /var/www/shared/%s_%s.settings.inc" % (repo, branch))
      print "===> Deleting /var/www/shared/%s_%s.settings.inc as we don't need it now" % (repo, branch)
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


  # If this site is being deployed from a custom branch job, we need to establish which dummy
  # vhost to use. If the ssl_enabled option is set in the config.ini file, use the
  # dummy_feature_branch_ssl.conf vhost. If it is not yet, we can use the
  # dummy_feature_branch.conf vhost.
  if buildtype == "custombranch":
    # Currently, this only works when the webserver in question is nginx.
    # TODO: make this work with nginx *and* apache
    if webserver == "nginx":
      # Copy Nginx vhost to server(s)
      print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/vhosts/%s/*' % webserver, '/etc/%s/sites-available' % webserver, mode=0755, use_sudo=True).failed:
        raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
      else:
        print "===> Dummy vhosts copied to app server(s)."
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
      # Copy Apache vhost to server(s)
      dummydir = webserver
      if webserver == 'httpd':
        dummydir = 'apache2'
      print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/vhosts/%s/*' % dummydir, '/etc/%s/sites-available' % webserver, mode=0755, use_sudo=True).failed:
        raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
      else:
        print "===> Dummy vhosts copied to app server(s)."
      #dummy_file = 'dummy_http.conf' if webserver == 'nginx' else 'dummy.conf'
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


