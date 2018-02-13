from fabric.api import *
from fabric.contrib.files import *
import os
import common.Services
import common.Utils

@task
# Small function to revert db
def _revert_db(alias, branch, build):
  run("if [ -f ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz ]; then drush -y @%s_%s sql-drop; zcat ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz | drush @%s_%s sql-cli; fi" % (alias, branch, build, alias, branch, alias, branch, build, alias, branch))


# Function to revert settings.php change for when a build fails and database is reverted
@task
def _revert_settings(alias, branch, build, buildtype, buildsite):
  with settings(warn_only=True):
    settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
    stable_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    replace_string = "/var/www/.*\.settings\.php"
    replace_with = "%s/www/sites/%s/%s.settings.php" % (stable_build, buildsite, buildtype)
    sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='', flags="i", shell=True)
    print "===> Reverted settings.php"

@task
def configure_site_mapping(repo, mapping, config):
  dontbuild = False

  if config.has_section("Sites"):
    print "===> Found a Sites section. Determining which sites to deploy..."
    sites = []
    for option in config.options("Sites"):
      line = config.get("Sites", option)
      if dontbuild:
        print "line: %s" % line

      line = line.split(',')
      if dontbuild:
        print "line split: %s" % line

      for sitename in line:
        sitename = sitename.strip()
        if dontbuild:
          print "sitename: %s" % sitename

        sites.append(sitename)
        if dontbuild:
          print "sites: %s" % sites

  if not sites:
    print "There isn't a Sites section, so we assume this is standard deployment."
    buildsite = 'default'
    alias = repo
    mapping.update({alias:buildsite})
  else:
    dirs = os.walk('www/sites').next()[1]
    for buildsite in dirs:
      if buildsite in sites:
        if buildsite == 'default':
          alias = repo
        else:
          alias = "%s_%s" % (repo, buildsite)
        mapping.update({alias:buildsite})
  
  print "Final mapping is: %s" % mapping
  return mapping


@task
def generate_multisite_url(alias, branch):
  return common.Utils.generate_url(None, alias, branch)


# Run drush cc all to clear any caches post-deployment
def drush_cache_clear(repo, branch, build, buildsite, drupal_version):
  print "===> Clearing Drupal caches"
  with settings(warn_only=True):
    with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite)):
      if drupal_version == '8':
        run("drush -y cr")
      else:
        run("drush -y cc all")


# Check for new sites to install and add them to an array, which is used
# in later functions when running first-time builds.
@task
@roles('app_primary')
def check_for_new_installs(repo, branch, build, mapping):
  sites_to_install = []
  for alias,buildsite in mapping.iteritems():
    url = generate_multisite_url(alias, branch)
    # Now check if we have a Drush alias with that name. If not, run an install
    with settings(hide('warnings', 'stderr'), warn_only=True):
      if run("drush sa | grep ^@%s_%s$ > /dev/null" % (alias, branch)).failed:
        print "Didn't find a Drush alias %s_%s so we'll install this new site %s" % (alias, branch, url)
        sites_to_install.append(buildsite)
  if sites_to_install:
    print "List of new sites to install: %s" % sites_to_install
  else:
    print "No new sites to install."
    sites_to_install = None

  return sites_to_install


@task
@roles('app_all')
def create_config_dir():
  print "Create /var/www/config if it doesn't exist and set correct ownership."
  sudo("mkdir -p /var/www/config")
  sudo("chown jenkins:www-data /var/www/config")


@task
@roles('app_all')
def new_site_live_symlink(repo, branch, build, mapping, sites):
  with settings(warn_only=True):
    if run("stat /var/www/live.%s.%s" % (repo, branch)).failed:
      # Symlink live codebase now
      print "Symlinking live codebase..."
      sudo("ln -nsf /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))


@task
@roles('app_all')
def new_site_files(repo, branch, build, mapping, sites):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      # Make shared directories, which is where assets will go
      #for alias,site in multisite_mapping.iteritems():
      print "===> Making the Drupal shared files dir and setting symlink for %s" % alias
      sudo("mkdir -p /var/www/shared/%s_%s_files" % (alias, branch))
      sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_files" % (alias, branch))
      sudo("chmod 2775 /var/www/shared/%s_%s_files" % (alias, branch))

      run("ln -nsf /var/www/shared/%s_%s_files /var/www/%s_%s_%s/www/sites/%s/files" % (alias, branch, repo, branch, build, buildsite))

      print "===> Making the private files dir"
      sudo("mkdir -p /var/www/shared/%s_%s_private_files" % (alias, branch))
      sudo("chown jenkins:www-data /var/www/shared/%s_%s_private_files" % (alias, branch))
      sudo("chmod 775 /var/www/shared/%s_%s_private_files" % (alias, branch))


@task
@roles('app_primary')
def new_site_create_database(repo, branch, build, buildtype, profile, mapping, sites, drupal_version, cluster, rds, config):

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

  drupal8 = False
  sitedir = "/var/www/%s_%s_%s/www" % (repo, branch, build)

  # Check if a db/ directory exists first.
  db_dir = False
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s -maxdepth 1 -type d -name db | egrep '.*'" % (repo, branch, build)).return_code == 0:
      db_dir = True

  dbscript = ""

  try_import = True
  if db_dir:
    dbscript = "mysqlprepare_multisite"
  else:
    try_import = False
    dbscript = "mysqlpreparenoimport_multisite"
    if cluster and rds:
      dbscript = "mysqlpreparenoimport_multisite_rds"

  if drupal_version == '8':
    drupal8 = True
    dbscript = "mysqlpreparenoimport_multisite"
    try_import = False

  print "===> Will use the script %s.sh for preparing the database" % dbscript

  script_dir = os.path.dirname(os.path.realpath(__file__))
  scripts_to_copy = [script_dir + '/../util/mysqlpreparenoimport_multisite.sh', script_dir + '/../util/mysqlprepare_multisite.sh', script_dir + '/../util/mysqlpreparenoimport_multisite_rds.sh']

  for each_script in scripts_to_copy:
    if put(each_script, '/home/jenkins', mode=0755).failed:
      raise SystemExit("Could not copy the database script to the application server, aborting because we won't be able to make a database")
    else:
      print "===> Database preparation script %s copied to %s:/home/jenkins/" % (each_script, env.host)


  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      # Set up the database: create it, create a GRANT, and import the database.
      # mysqlprepare.sh will pick a database name, incrementing a digit if a database already exists with the same name
      # If a filename of <buildsite>.sql.bz2 exists, import that file.
      print "===> Preparing the databases"
      newpass = common.Utils._gen_passwd()
      # Import database if it exists
      if drupal8:
        sudo("/home/jenkins/%s.sh %s %s %s %s %s %s" % (dbscript, repo, newpass, sitedir, buildtype, buildsite, drupal8))
        if db_dir:
          if run("stat /var/www/%s_%s_%s/db/%s.sql.bz2" % (repo, branch, build, buildsite)).failed:
            print "Cannot find a %s.sql.bz2 file. A minimal D8 site has already been installed, so carry on with deployment." % buildsite
          else:
            with cd("%s/sites/%s" % (sitedir, buildsite)):
              sudo("drush -y sql-drop")
              if sudo("bzcat /var/www/%s_%s_%s/db/%s.sql.bz2 | drush -y sql-cli" % (repo, branch, build, buildsite)).failed:
                raise SystemError("Could not import database for %s site. Aborting build." % buildsite)
      else:
        if try_import:
          if run("stat /var/www/%s_%s_%s/db/%s.sql.bz2" % (repo, branch, build, buildsite)).failed:
            print "Cannot find a %s.sql.bz2 file. We'll install without importing a database." % buildsite
            try_import = False
            dbscript = "mysqlpreparenoimport_multisite"
            if cluster and rds:
              dbscript = "mysqlpreparenoimport_multisite_rds"
          else:
            sudo("bunzip2 /var/www/%s_%s_%s/db/%s.sql.bz2" % (repo, branch, build, buildsite))
            # mysqlprepare.sh <databasename> <databasepass> <site_root> <branch> <dumpfile> <url>
            sudo("/home/jenkins/%s.sh %s %s /var/www/%s_%s_%s/www %s $(find /var/www/%s_%s_%s/db -type f -name %s.sql) %s" % (dbscript, alias, newpass, repo, branch, build, branch, repo, branch, build, buildsite, buildsite))

        if not try_import:
          if dbscript == "mysqlpreparenoimport_multisite_rds":
            sudo("/home/jenkins/%s.sh %s %s %s /var/www/%s_%s_%s/www %s %s %s %s" % (dbscript, alias, dbhost, newpass, repo, branch, build, branch, buildsite, list_of_app_servers, drupal8))
          else:
            sudo("/home/jenkins/%s.sh %s %s /var/www/%s_%s_%s/www %s %s" % (dbscript, alias, newpass, repo, branch, build, branch, buildsite))

      sudo("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/config/%s_%s.settings.inc" % (repo, branch, build, buildsite, alias, branch))


@task
@roles('app_all')
def new_site_copy_settings(repo, branch, build, mapping, sites):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      # Fix perms on subdir
      sudo("chmod 755 /var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite))

      # Improve perms on settings.php
      sudo("chown jenkins:www-data /var/www/config/%s_%s.settings.inc" % (alias, branch))
      sudo("chmod 644 /var/www/config/%s_%s.settings.inc" % (alias, branch))
      sudo("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))


@task
@roles('app_primary')
def new_site_force_dbupdate(repo, branch, build, mapping, sites):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      # Force a drush updatedb on the site - we may not be running drush updatedb in general, but we should on fresh sites
      with settings(warn_only=True):
        with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite)):
          run("drush -y updatedb")


@task
@roles('app_all')
def new_site_build_vhost(repo, branch, mapping, sites, webserverport):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      url = generate_multisite_url(alias, branch)
      # Some quick clean-up from earlier, delete the 'shared' settings.inc
      with settings(warn_only=True):
        if run("stat /var/www/shared/%s_%s.settings.inc" % (alias, branch)).return_code == 0:
          sudo("rm /var/www/shared/%s_%s.settings.inc" % (alias, branch))
          print "===> Deleting /var/www/shared/%s_%s.settings.inc as we don't need it now" % (alias, branch)

      # Work out whether we are running Apache or Nginx (compensating for RedHat which uses httpd as name)
      # Assume Nginx by default
      webserver = "nginx"
      # Copy Nginx vhost to server(s)
      print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/vhosts/%s/*' % webserver, '/etc/%s/sites-available' % webserver, mode=0755, use_sudo=True).failed:
        raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
      else:
        print "===> Dummy vhosts copied to app server(s)."
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

      sudo("cp /etc/%s/sites-available/dummy.conf /etc/%s/sites-available/%s.conf" % (webserver, webserver, url))
      sudo("sed -i s/dummyfqdn/%s/g /etc/%s/sites-available/%s.conf" % (url, webserver, url))
      sudo("sed -i s/dummyport/%s/g /etc/%s/sites-available/%s.conf" % (webserverport, webserver, url))
      sudo("sed -i s/dummy/%s.%s/g /etc/%s/sites-available/%s.conf" % (repo, branch, webserver, url))
      sudo("ln -s /etc/%s/sites-available/%s.conf /etc/%s/sites-enabled/%s.conf" % (webserver, url, webserver, url))
      url_output = url.lower()
      print "***** Your buildsite is http://%s *****" % url_output


@task
@roles('app_all')
def generate_drush_alias(repo, branch, mapping, sites):
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/drush_alias_multisite.sh', '/home/jenkins', mode=0755).failed:
    raise SystemExit("Could not copy the drush script to the application server, aborting because we won't be able to make a drush alias")
  else:
    for alias,buildsite in mapping.iteritems():
      if buildsite in sites:
        url = generate_multisite_url(alias, branch)

        # Generate a Drush alias file for this site
        print "===> Generating Drush alias"
        sudo("/home/jenkins/drush_alias_multisite.sh %s %s %s /var/www/live.%s.%s/www" % (alias, url, branch, repo, branch))


@task
@roles('app_primary')
def generate_drush_cron(repo, branch, mapping, sites):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/drush_cron', '/home/jenkins', mode=0755).failed:
        print "===> Could not copy the drush_cron script to the application server, cron will not be generated for this site"
      else:
        print "===> drush_cron script copied to %s:/home/jenkins/drush_cron" % env.host
        # Generate a crontab for running drush cron on this site
        print "===> Generating Drush cron for this site if it isn't there already"
        sudo("bash /home/jenkins/drush_cron %s %s" % (alias, branch))


@task
@roles('app_primary')
def new_site_fix_perms(repo, branch, mapping, sites, drupal_version):
  for alias,buildsite in mapping.iteritems():
    if buildsite in sites:
      if drupal_version == "8":
        # If the site is Drupal 8, after the initial build, the config directory will have incorrect permissions, which is not ideal.
        sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_files" % (alias, branch))
        sudo("chmod 2775 /var/www/shared/%s_%s_files" % (alias, branch))


# Take a database backup
@task
@roles('app_primary')
def backup_db(repo, branch, build, mapping, sites):
  if sites is None:
      sites = []

  print "===> Ensuring backup directory exists"
  with settings(warn_only=True):
    if run("mkdir -p ~jenkins/dbbackups").failed:
      raise SystemExit("Could not create directory ~jenkins/dbbackups! Aborting early")
  failed_backup = False
  for alias,buildsite in mapping.iteritems():
    if buildsite not in sites:
      print "===> Taking a database backup..."
      with settings(warn_only=True):
        if run("drush @%s_%s sql-dump --skip-tables-key=common | gzip > ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz; if [ ${PIPESTATUS[0]} -ne 0 ]; then exit 1; else exit 0; fi" % (alias, branch, alias, branch, build)).failed:
          failed_backup = True
        else:
          failed_backup = False
    else:
      print "%s is a new site, so not running backup_db function on it." % buildsite

  if failed_backup:
    raise SystemExit("Could not take database backup prior to launching new build! Aborting early")


# Adjust shared files symlink
@task
@roles('app_all')
def adjust_files_symlink(repo, branch, build, mapping, sites):
  if sites is None:
      sites = []
  for alias,buildsite in mapping.iteritems():
    if buildsite not in sites:
      print "===> Setting the symlink for the files directory of %s" % buildsite
      sudo("ln -nsf /var/www/shared/%s_%s_files/ /var/www/%s_%s_%s/www/sites/%s/files" % (alias, branch, repo, branch, build, buildsite))
    else:
      print "%s is a new site, so not running adjust_files_symlink function on it." % buildsite


# Adjust settings.php. Copy the relevant file based on the branch, delete the rest.
@task
@roles('app_all')
def adjust_settings_php(repo, branch, build, buildtype, mapping, sites):
  if sites is None:
      sites = []

  # We do not want settings.inc on NAS in case it faiils
  # This can be removed at some later date because initial_build() takes care of it going forwards
  # For now this is just to catch "first build" scenarios where a config directory is required but missing
  with settings(warn_only=True):
    if run("stat /var/www/config").failed:
      # No "config" directory
      sudo("mkdir --mode 0755 /var/www/config")
      sudo("chown jenkins:www-data /var/www/config")

  for alias,buildsite in mapping.iteritems():
    if buildsite not in sites:
      
      # In some cases it seems jenkins loses write permissions to the 'default' directory
      # Let's make sure!
      sudo("chmod -R 775 /var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite))

      # Process for adjusting settings.php is this:
      # 1. Check if a repo_branch.settings.inc file exists in /var/www/config
      # 2. If it doesn't, check if sites/default/settings.php exists.
      # 3. If that doesn't, check if sites/default/$branch.settings.php exists, as a last resort.
      # 4. If sites/default/$buildtype.settings.php doesn't exist, raise a SystemExit and get out.
      # 5. If sites/default/$buildtype.settings.php DOES exist, add a commented line to the bottom of it to say it copied to settings.inc and to not include sites/default/$buildtype.settings.php in it, otherwise there'd be duplicate config values.
      # 6. If sites/default/settings.php exists, see if it contains the file_exists(sites/default/$branch.settings.php) check, and if it doesn't, append that check to the bottom of settings.php.
      # 7. If a settings.inc file was found:
      # 8. Check if it contains the comment from #5 and if it does, do NOT append file_exists() check to bottom of file.
      # 9. If comment from #5 is not found, append file_exists() check to bottom of file
      # 10. If there's no sites/default/settings.php, symlink in settings.inc file.

      with settings(warn_only=True):
        # 1a. First check if the settings.inc file exists in 'config'
        if run("stat /var/www/config/%s_%s.settings.inc" % (alias, branch)).failed:
          #############################################
          # TODO: This if can be removed later once the 'config' approach is established
          # 1b. Maybe we have a settings.inc file in 'shared' from an older build
          if run("stat /var/www/shared/%s_%s.settings.inc" % (alias, branch)).failed:
            # 2. We didn't find the shared file. Check if sites/$buildsite/settings.php exists.
            print "The shared settings file /var/www/shared/%s_%s.settings.inc was not found, nor was /var/www/config/%s_%s.settings.inc. We'll try and move a sites/%s/settings.php file there, if it exists." % (alias, branch, alias, branch, buildsite)
            if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, buildsite)).failed:
              # 3. Doesn't look like sites/$buildside/settings.php exists. We'll see if a sites/$buildside/$branch.settings.php file exists instead, as a last resort.
              print "We couldn't find /var/www/%s_%s_%s/www/sites/%s/settings.php, so we'll search for a branch specific file as a last resort." % (repo, branch, build, buildsite)
              if run("stat /var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, buildsite, buildtype)).failed:
                # 4. We couldn't find a sites/$buildsite/$buildtype.settings.php file either. This isn't right, so let's raise an error and get out of here.
                raise SystemExit("Couldn't find any settings.php whatsoever! As it's unlikely we'll be able to bootstrap a site, we're going to abort early. TIP: Add a /var/www/config/%s_%s.settings.inc file manually and do a file_exists() check for /var/www/%s_%s_%s/www/sites/%s/%s.settings.php and if it exists, include it. Then symlink that to /var/www/%s_%s_%s/www/sites/%s/settings.php." % (repo, branch, repo, branch, build, buildsite, buildtype, repo, branch, build, buildsite))
              else:
                # 5. We DID find sites/$buildsite/$buildtype.settings.php
                print "We found /var/www/%s_%s_%s/www/sites/%s/%s.settings.php, so we'll add a commented line at the bottom of it to indicate it's copied to /var/www/config/%s_%s.settings.inc. This will prevent %s.settings.php being included in the settings.inc file in subsequent builds. We'll also move it to /var/www/config/%s_%s.settings.inc." % (repo, branch, build, buildsite, buildtype, alias, branch, buildtype, alias, branch)
                settings_file = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, buildsite, buildtype)
                append(settings_file, '# Copied from branch settings')
                sudo("mv /var/www/%s_%s_%s/www/sites/%s/%s.settings.php /var/www/config/%s_%s.settings.inc" % (repo, branch, build, buildsite, buildtype, alias, branch))
                sudo("chown jenkins:www-data /var/www/config/%s_%s.settings.inc" % (alias, branch))
                sudo("chmod 664 /var/www/config/%s_%s.settings.inc" % (alias, branch))
                run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))
            else:
              # 6. We found sites/%buildsite/settings.php. Let's see if it's checking for sites/$buildsite/$buildtype.settings.php. If it's not, we'll add the check to the bottom of the file.
              contain_string = "if (file_exists($file)) {"
              settings_file = "/var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, buildsite)
              does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
              if not does_contain:
                #append_string = """$file = '/var/www/live.%s.%s/www/sites/default/%s.settings.php';
                append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include_once($file);
}""" % (repo, branch, build, buildsite, buildtype)
                append(settings_file, append_string, use_sudo=True)
                print "%s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file
              else:
                #print "%s already has a file_exists() check, so it wasn't appened to the bottom of the settings.inc file." % settings_file
                print "%s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
                replace_string = "/var/www/.*\.settings\.php"
                replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, buildsite, buildtype)
                sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='.bak', flags="i", shell=False)
          else:
            #############################################
            # TODO: This whole if / else can be removed once the 'config' approach is established
            # 7a. We found a shared settings.inc file in /var/www/shared. We need to copy it to /var/www/config.
            print "We found /var/www/shared/%s_%s.settings.inc. We need to copy it to /var/www/config." % (alias, branch)
            run("cp -a /var/www/shared/%s_%s.settings.inc /var/www/config/%s_%s.settings.inc" % (alias, branch, alias, branch))
            contain_string = '# Copied from branch settings'
            settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
            does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
            if does_contain:
              # 8. The shared settings.inc contains the comment from #5. Therefore, we won't add a file_exists($buildtype.settings.php) check.
              print "%s contains '%s', so we won't append a file_exists() check and include_once. This is because the settings.php file was copied from sites/%s/%s.settings.php and it wouldn't make sense to include itself." % (settings_file, contain_string, buildsite, buildtype)
            else:
              # 9. The shared settings.inc does not contain a comment (from #5), so we'll see if we need to append a file_exists() check.
              print "%s does not contain '%s', so we'll check if we need to append a file_exists() check to settings.inc." % (settings_file, contain_string)
              contain_string = "if (file_exists($file)) {"
              does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
              if not does_contain:
                #append_string = """$file = '/var/www/live.%s.%s/www/sites/default/%s.settings.php';
                append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include_once($file);
}""" % (repo, branch, build, buildsite, buildtype)
                append(settings_file, append_string, use_sudo=True)
                print "%s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file
              else:
                #print "%s already has a file_exists() check, so it wasn't appened to the bottom of the settings.inc file." % settings_file
                print "%s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
                replace_string = "/var/www/.*\.settings\.php"
                replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, buildsite, buildtype)
                sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='.bak', flags="i", shell=False)
            # 10. Let's see if there's a settings.php file in sites/default. If not, we'll symlink in our shared settings.inc.
            if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, buildsite)).failed:
              print "There's a settings.inc file, but no main settings.php file. We'll symlink in our shared file."
              run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))
            else:
              print "We found a settings.inc file AND a main settings.php file. We'll move settings.php to settings.php.bak and symlink in the settings.inc file."
              sudo("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/%s_%s_%s/www/sites/%s/settings.php.bak" % (repo, branch, build, buildsite, repo, branch, build, buildsite))
              run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))
            #############################################
        else:
          # 7b. We found a settings.inc file in /var/www/config. Let's see if we first should append anything to it, and then if we need to.
          contain_string = '# Copied from branch settings'
          settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
          does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
          if does_contain:
            # 8. The settings.inc contains the comment from #5. Therefore, we won't add a file_exists($buildtype.settings.php) check.
            print "%s contains '%s', so we won't append a file_exists() check and include_once. This is because the settings.php file was copied from sites/%s/%s.settings.php and it wouldn't make sense to include itself." % (settings_file, contain_string, buildsite, buildtype)
          else:
            # 9. The settings.inc does not contain a comment (from #5), so we'll see if we need to append a file_exists() check.
            print "%s does not contain '%s', so we'll check if we need to append a file_exists() check to settings.inc." % (settings_file, contain_string)
            contain_string = "if (file_exists($file)) {"
            does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
            if not does_contain:
              #append_string = """$file = '/var/www/live.%s.%s/www/sites/default/%s.settings.php';
              append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include_once($file);
}""" % (repo, branch, build, buildsite, buildtype)
              append(settings_file, append_string, use_sudo=True)
              print "%s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file
            else:
              #print "%s already has a file_exists() check, so it wasn't appened to the bottom of the settings.inc file." % settings_file
              print "%s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
              replace_string = "/var/www/.*\.settings\.php"
              replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, buildsite, buildtype)
              sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='.bak', flags="i", shell=False)
          # 10. Let's see if there's a settings.php file in sites/default. If not, we'll symlink in our settings.inc.
          if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, buildsite)).failed:
            print "There's a settings.inc file, but no main settings.php file. We'll symlink in our settings.inc file."
            run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))
          else:
            print "We found a settings.inc file AND a main settings.php file. We'll move settings.php to settings.php.bak and symlink in the settings.inc file."
            sudo("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/%s_%s_%s/www/sites/%s/settings.php.bak" % (repo, branch, build, buildsite, repo, branch, build, buildsite))
            run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, buildsite))
    else:
      print "%s is a new site, so not running adjust_settings_php function on it." % buildsite


# Run a drush status against that build
@task
@roles('app_primary')
def drush_status(repo, branch, build, buildtype, mapping, sites, revert=False, revert_settings=False):
  if sites is None:
      sites = []

  print "===> Running a drush status test"
  for alias,buildsite in mapping.iteritems():
    if buildsite not in sites:
      with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite)):
        with settings(warn_only=True):
          if run("drush status | egrep 'Connected|Successful'").failed:
            print "Could not bootstrap the database!"
            if revert == False and revert_settings == True:
              _revert_settings(alias, branch, build, buildtype, buildsite)
            else:
              if revert:
                print "Reverting the database..."
                _revert_db(alias, branch, build)
                _revert_settings(alias, branch, build, buildtype, buildsite)
            raise SystemExit("Could not bootstrap the database on this build! Aborting")
       
          if run("drush status").failed:
            if revert == False and revert_settings == True:
              _revert_settings(alias, branch, build, buildtype, buildsite)
            else:
              if revert:
                print "Reverting the database..."
                _revert_db(alias, branch, build)
                _revert_settings(alias, branch, build, buildtype, buildsite)
            raise SystemExit("Could not bootstrap the database on this build! Aborting")
    else:
      print "%s is a new site, so not running drush_status function on it." % buildsite


# Run drush updatedb to apply any database changes from hook_update's
@task
@roles('app_primary')
def drush_updatedb(repo, branch, build, buildtype, mapping, sites, drupal_version):
  if sites is None:
      sites = []

  print "===> Running any database hook updates"
  with settings(warn_only=True):
    # Apparently APC cache can interfere with drush updatedb expected results here. Clear any chance of caches
    common.Services.clear_varnish_cache()
    common.Services.clear_php_cache()
    for alias,buildsite in mapping.iteritems():
      if buildsite not in sites:
        with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, buildsite)):
          print "===> Clearing cache on %s before drush updatedb" % buildsite
          if drupal_version == '8':
            run("drush -y cr")
          else:
            run("drush -y cc all")
          # Take site offline
          print "===> Taking %s offline to run database updates" % buildsite
          if drupal_version == '8':
            run("drush -y state-set system.maintenancemode 1")
          else:
            run("drush -y vset maintenance_mode 1")
          # Run the updates
          print "===> Running any database hook updates on %s" % buildsite
          if run("drush -y updatedb").failed:
            print "Could not apply database updates! Reverting this database."
            _revert_db(alias, branch, build)
            _revert_settings(alias, branch, build, buildtype, buildsite)
            raise SystemExit("Could not apply database updates! Reverted database. Site remains on previous build.")
          # Take site online
          print "===> Bring %s online again" % buildsite
          if drupal_version == '8':
            if run("drush -y state-set system.maintenancemode 0").failed:
              print "Could not set the site back online! Reverting database. We need to exit out of deployment so the live symlink isn't adjusted."
              _revert_db(alias, branch, build)
              _revert_settings(alias, branch, build, buildtype, buildsite)
              raise SystemExit("Could not set the site back online! Database was reverted and deployment aborted so live symlink was not adjusted.")
          else:
            if run("drush -y vset maintenance_mode 0").failed:
              print "Could not set the site back online! Reverting database. We need to exit out of deployment so the live symlink isn't adjusted."
              _revert_db(alias, branch, build)
              _revert_settings(alias, branch, build, buildtype, buildsite)
              raise SystemExit("Could not set the site back online! Database was reverted and deployment aborted so live symlink was not adjusted.")
      else:
        print "%s is a new site, so not running drush_updatedb function on it." % buildsite


# Manage or setup the 'environment_indicator' Drupal module, if it exists in the build
# See RS11494
def environment_indicator(repo, branch, build, buildtype):
  # Check if the module exists in the build
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s/www -type d -name environment_indicator | egrep '.*'" % (repo, branch, build)).return_code == 0:
      environment_indicator_module = True
    else:
      environment_indicator_module = False

  # The module exists, now check if it's configured
  if environment_indicator_module:
    # Set up colours
    if buildtype == "dev":
      environment_indicator_color = "#00E500"
    elif buildtype == "stage":
      environment_indicator_color = "#ff9b01"
    else:
      # We don't know this buildtype, let's assume the worst and treat it as prod
      environment_indicator_color = "#ff0101"

    # Append the config to settings.inc if not already present
    # Use of Fabfile's 'append()' is meant to silently ignore if the text already exists in the file. So we don't bother
    # checking for it - if it exists but with a different value, appending will overrule the previous entry (maybe a bit
    # ugly or confusing when reading the file, but saves a horrible amount of kludge here grepping for existing entries)
    if drupal7:
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$conf['environment_indicator_overwrite'] = 'TRUE';", True)
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$conf['environment_indicator_overwritten_name'] = '%s';" % buildtype, True)
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$conf['environment_indicator_overwritten_color'] = '%s';" % environment_indicator_color, True)
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$conf['environment_indicator_overwritten_text_color'] = '#ffffff';", True)

    if drupal8:
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$config['environment_indicator.indicator']['name'] = '%s';" % buildtype, True)
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$config['environment_indicator.indicator']['bg_color'] = '%s';" % environment_indicator_color, True)
      append("/var/www/shared/%s_%s.settings.inc" % (repo, branch), "$config['environment_indicator.indicator']['fg_color'] = '#ffffff';", True)

    if drupal7 or drupal8:
      # Enable the module (if not already enabled)
      with cd("/var/www/%s_%s_%s/www/sites/default" % (repo, branch, build)):
        run("drush -y en environment_indicator")
    if drupal6:
      print "Drupal 6 site. Not setting up environment_indicator at this time.."
  else:
    print "The environment_indicator module was not present. Moving on..."


@task
@roles('app_primary')
def drush_fra(repo, branch, build, buildtype, mapping, sites, drupal_version):
  if sites is None:
      sites = []

  for alias,buildsite in mapping.iteritems():
    if buildsite not in sites:
      print "===> Reverting all features on %s..." % buildsite
      with settings(warn_only=True):
        if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y fra --force'" % (repo, branch, build, buildsite)).failed:
          print "Could not revert features!"
          _revert_db(alias, branch, build)
          _revert_settings(alias, branch, build, buildtype, buildsite)
          raise SystemExit("Could not revert features! Site remains on previous build")
        else:
          drush_cache_clear(repo, branch, build, buildsite, drupal_version)
    else:
      print "%s is a new site, so not running drush_fra function on it." % buildsite


# Set the username and password of user 1 to something random if the buildtype is 'prod'
@task
@roles('app_primary')
def secure_admin_password(repo, branch, build, mapping, drupal_version):
  for alias,buildsite in mapping.iteritems():
    print "===> Setting secure username and password for uid 1 on %s site..." % buildsite
    u1pass = common.Utils._gen_passwd(20)
    u1name = common.Utils._gen_passwd(20)
    with cd('/var/www/%s_%s_%s/www/sites/%s' % (repo, branch, build, buildsite)):
      with settings(warn_only=True):
        if drupal_version == '8':
          run('drush sqlq "UPDATE users_field_data SET name = \'%s\' WHERE uid = 1"' % u1name)
        else:
          run('drush sqlq "UPDATE users SET name = \'%s\' WHERE uid = 1"' % u1name)
        run("drush upwd %s --password='%s'" % (u1name, u1pass))
