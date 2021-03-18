from fabric.api import *
from fabric.contrib.files import *
import random
import string
import time
import sys
# Custom Code Enigma modules
import common.ConfigFile
import common.Services
import common.Utils


# Take a database backup of the staging site before we replace its database.
@task
def backup_db(shortname, staging_branch, stage_drupal_root, site='default', extra=''):
  now = time.strftime("%Y%m%d%H%M%S", time.gmtime())
  print "===> Ensuring backup directory exists"
  run("mkdir -p ~jenkins/dbbackups")
  print "===> Taking a database backup of the Drupal database..."
  run("cd %s && drush -l %s sql-dump --result-file=/dev/stdout --extra=%s | bzip2 -f > ~jenkins/dbbackups/%s_%s_prior_to_sync_%s.sql.bz2" % (stage_drupal_root, site, extra, shortname, staging_branch, now))


# Sync uploaded assets from production to staging
@task
def sync_assets(orig_host, shortname, staging_shortname, staging_branch, prod_branch, config, app_dir, remote_files_dir=None, staging_files_dir=None, sync_dir=None, site='default', alias=None):
  # Switch the credentials with which to connect to production
  env.host = config.get(shortname, 'host')
  env.user = config.get(shortname, 'user')
  env.host_string = '%s@%s' % (env.user, env.host)

  prod_site_exists = common.Utils.get_previous_build(shortname, prod_branch, 0)
  if prod_site_exists is None:
    raise SystemError("Couldn't find this site with Drush alias %s_%s in production in order to sync its files to staging! Aborting." % (shortname, prod_branch))

  prod_drupal_root = prod_site_exists + '/' + app_dir

  if sync_dir is None:
    sync_dir = '/tmp'

  # Sync down the assets to the Jenkins machine, before sending them upstream to the staging server.
  print "===> Finding the remote files directories to rsync from..."
  if run('cd %s && drush -l %s dd files' % (prod_drupal_root, site)).failed:
    raise SystemError("Couldn't find this site %s with Drush alias %s_%s in production in order to sync its assets to staging! Aborting." % (site, shortname, prod_branch))
  else:
    if remote_files_dir is None:
      remote_files_dir = run("cd %s && drush -l %s dd files" % (prod_drupal_root, site))
    if site == 'default':
      sync_dir_name = staging_shortname
    else:
      sync_dir_name = staging_shortname + '_' + site
    local("rsync -e 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' -aHPv %s@%s:%s/ %s/%s_drupal_files/" % (env.user, env.host, remote_files_dir, sync_dir, sync_dir_name))

  # Switch the host to the staging server, it's time to send the assets upstream
  env.host_string = orig_host

  print "===> Running an rsync of the production Drupal's 'files' directory to our staging site..."
  # Temporarily force the perms to be owned by jenkins on staging, so that we can overwrite files
  # First check - is the files dir a symlink?
  if staging_files_dir is None:
    staging_files_dir = "/var/www/shared/%s_%s_files" % (sync_dir_name, staging_branch)
    with settings(warn_only=True):
      if sudo("readlink %s" % staging_files_dir).return_code == 0:
        staging_files_dir = sudo("readlink %s" % staging_files_dir)

  sudo("chown -R jenkins %s" % staging_files_dir)
  # Rsync up the files
  local("rsync -aHPv %s/%s_drupal_files/ %s:%s" % (sync_dir, sync_dir_name, env.host_string, staging_files_dir))
  # Fix up the perms
  sudo("chown -R www-data:jenkins %s" % staging_files_dir)
  sudo("chmod 2775 %s" % staging_files_dir)
  sudo("find %s -type d -print0 | xargs -r -0 chmod 2775" % staging_files_dir)
  sudo("find %s -type f -print0 | xargs -r -0 chmod 664" % staging_files_dir)


# Sync databases from production to staging
@task
def sync_db(orig_host, shortname, staging_shortname, staging_branch, prod_branch, fresh_database, sanitise, sanitised_password, sanitised_email, config, drupal_version, stage_drupal_root, app_dir, site='default', db_import_method='drush', extra=''):
  now = time.strftime("%Y%m%d%H%M%S", time.gmtime())
  # Switch to operating to the production server as a target
  env.host = config.get(shortname, 'host')
  env.user = config.get(shortname, 'user')
  env.host_string = '%s@%s' % (env.user, env.host)
  print "===> Host string is %s" % env.host_string

  # Local directory store database dumps before sending them back to the original host that needs them
  local("mkdir -p /tmp/dbbackups")

  print "===> Ensuring backup directory exists in production"
  run("mkdir -p ~jenkins/dbbackups")

  # Abort early if we couldn't bootstrap the database in production
  prod_site_exists = common.Utils.get_previous_build(shortname, prod_branch, 0)
  if prod_site_exists is None:
    raise SystemError("Couldn't find this site with Drush alias %s_%s in production in order to sync its database to staging! Aborting." % (shortname, prod_branch))

  # Unless we have explicitly been told to fetch a fresh database (make a dump),
  # try and fetch the latest available existing backup. This will speed up the sync
  # as well as avoid unnecessary stress on the CPU, possible database locks etc of
  # the production system

  remote_database = False
  prod_drupal_root = prod_site_exists + '/' + app_dir
  if fresh_database == 'no':
    print "===> Looking for an existing database backup..."
    # Enumerate the database name
    dbname = run("cd %s && drush -l %s status | egrep \"DB name|Database name\" | awk {'print $4'} | head -1" % (prod_drupal_root, site))
    # Look for a database backup
    with settings(warn_only=True):
      print "===> Checking for /opt/dbbackups directory..."
      if sudo("find /opt -maxdepth 1 -type d -name dbbackups").return_code == 0:
        print "===> Found /opt/dbbackups. That must mean the database backup is available on this server. Let's check..."
        if sudo("test -z `find /opt/dbbackups/$(hostname -f)/%s/ -type f -ctime -1`" % dbname).return_code == 0:
          # We didn't find a database backup. Switch to taking a fresh one either way.
          print "===> Could not find a database backup on the server. We'll take a fresh backup instead..."
          fresh_database = 'yes'
      else:
        print "===> Could not find /opt/dbbackups. Before we assume there's not database backup, it could be the database backup is on a separate database server. Let's check..."
        print "===> Getting database host..."
        dbhost = run("cd %s && drush -l %s status | egrep \"DB host|Database host\" | awk {'print $4'} | head -1" % (prod_drupal_root, site))
        if dbhost == 'localhost':
          fresh_database = 'yes'
        else:
          remote_database = True

    if fresh_database == 'no':
      copy_db = True
      if remote_database:
        env.host_string = '%s@%s' % (env.user, dbhost)
        print "Changing host. Host string is %s" % env.host_string
        run("mkdir -p ~jenkins/dbbackups")

        with settings(warn_only=True):
          if sudo("test -z `find /opt/dbbackups/$(hostname -f)/%s/ -type f -ctime -1`" % dbname).return_code == 0:
            # We didn't find a database backup. Switch to taking a fresh one either way.
            print "===> Could not find a database backup on the server. We'll take a fresh backup instead..."
            fresh_database = 'yes'
            copy_db = False

      if copy_db:
        # Enumerate the filename of the latest backup
        database_file = sudo("find /opt/dbbackups/`hostname -f`/%s/ -type f -ctime -1 | tail -1" % dbname)
        # Copy the database backup somewhere that jenkins user can scp it down without sudo
        sudo("cp %s /home/jenkins/dbbackups/drupal_%s_%s.sql.bz2" % (database_file, shortname, now))
        sudo("chown jenkins:jenkins /home/jenkins/dbbackups/drupal_%s_%s.sql.bz2" % (shortname, now))

  if fresh_database == 'yes':
    print "===> Making database backups from production"
    # Take a fresh database backup and store it somewhere we can scp it down as jenkins
    # Ensure we sanitise it first if necessary - which requires a custom mysqldump command
    if sanitise == 'yes':
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if drupal_version == 8:
        obfuscate_script = "drupal8-obfuscate.rb"
      else:
        obfuscate_script = "drupal-obfuscate.rb"
      if put(script_dir + '/../util/%s' % obfuscate_script, '/home/jenkins', mode=0755).failed:
        raise SystemExit("Could not copy the obfuscate script to the application server, aborting as we cannot safely sanitise the live data")
      else:
        print "===> Obfuscate script copied to %s:/home/jenkins/%s - obfuscating data" % (env.host, obfuscate_script)
        with settings(hide('running', 'stdout', 'stderr')):
          with cd('%s' % prod_drupal_root):
            dbname = run("drush -l %s status | egrep \"DB name|Database name\" | awk {'print $4'} | head -1" % site)
            dbuser = run("drush -l %s status | egrep \"DB user|Database user\" | awk {'print $4'} | head -1" % site)
            dbpass = run("drush --show-passwords -l %s status | egrep \"DB pass|Database pass\" | awk {'print $4'} | head -1" % site)
            dbhost = run("drush -l %s status | egrep \"DB host|Database host\" | awk {'print $4'} | head -1" % site)
          run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /home/jenkins/%s | bzip2 -f > ~jenkins/dbbackups/drupal_%s_%s.sql.bz2' % (dbuser, dbpass, dbhost, dbname, obfuscate_script, shortname, now))
    else:
      run('cd %s && drush -l %s sql-dump --result-file=/dev/stdout --extra=%s | bzip2 -f > ~jenkins/dbbackups/drupal_%s_%s.sql.bz2' % (prod_drupal_root, site, extra, shortname, now))
    print "===> Fetching the drupal database backup from production..."

  # Fetch the database backup from prod
  get('~/dbbackups/drupal_%s_%s.sql.bz2' % (shortname, now), '/tmp/dbbackups/drupal_%s_%s_from_prod.sql.bz2' % (shortname, now))
  run('rm ~/dbbackups/drupal_%s_%s.sql.bz2' % (shortname, now))

  # Switch back to operating to the staging server as a target
  env.host_string = orig_host
  print "===> Host string is %s" % env.host_string

  print "===> Sending database dumps to destination server"
  local('scp /tmp/dbbackups/drupal_%s_%s_from_prod.sql.bz2 %s:~/dbbackups/' % (shortname, now, env.host_string))

  print "===> Check the production database has actually been copied down"
  if run("stat /home/jenkins/dbbackups/drupal_%s_%s_from_prod.sql.bz2" % (shortname, now)).failed:
    # Clean up local copy
    local('rm /tmp/dbbackups/drupal_%s_%s_from_prod.sql.bz2' % (shortname, now))
    raise SystemExit("Nope, production database hasn't been copied down. Abort now, as the stage site will go down if we proceed.")

  # Now we've verified success we can clean up the local DB archive
  local('rm /tmp/dbbackups/drupal_%s_%s_from_prod.sql.bz2' % (shortname, now))

  print "===> Importing the drupal database"
  # Need to drop all tables first in case there are existing tables that have to be ADDED from an upgrade
  run("cd %s && drush -l %s -y sql-drop" % (stage_drupal_root, site))
  # Reimport from backup
  # Ignore errors because we will want to remove the database dump regardless of whether this succeeded,
  # *in case* it contains sensitive data
  with settings(warn_only=True):
    with cd('%s' % stage_drupal_root):
      if db_import_method == "mysql":
        # Get the destination database name so we can use mysql to import the source database
        dest_db_name = run("cd %s && drush -l %s status | egrep \"DB name|Database name\" | awk {'print $4'} | head -1" % (stage_drupal_root, site))
        import_command = "mysql --defaults-file=/etc/mysql/debian.cnf %s" % dest_db_name
      else:
        import_command = "drush -l %s sql-cli" % site
      sudo("bzcat /home/jenkins/dbbackups/drupal_%s_%s_from_prod.sql.bz2 | %s " % (shortname, now, import_command))
      # Set all users to the supplied e-mail address/password for stage testing
      if sanitise == 'yes':
        if sanitised_password is None:
          sanitised_password = common.Utils._gen_passwd()
        if sanitised_email is None:
          sanitised_email = 'example.com'
        run("drush -l %s -y sql-sanitize --sanitize-email=%s+%%uid@%s --sanitize-password=%s" % (site, shortname, sanitised_email, sanitised_password))
        print "===> Data sanitised, email domain set to %s, passwords set to %s" % (sanitised_email, sanitised_password)
  run("rm ~/dbbackups/drupal_%s_%s_from_prod.sql.bz2" % (shortname, now))


# Run drush updatedb to apply any database changes from hook_update's
@task
def drush_updatedb(orig_host, shortname, staging_branch, stage_drupal_root, site='default'):
  env.host_string = orig_host
  print env.host_string
  print "===> Running any database hook updates on %s site" % site
  run("cd %s && drush -l %s -y updatedb" % (stage_drupal_root, site))


# Keep calm and clear the cache
@task
def clear_caches(orig_host, shortname, staging_branch, drupal_version, stage_drupal_root, site='default'):
  env.host_string = orig_host
  print "===> Clearing caches"
  with cd('%s' % stage_drupal_root):
    if drupal_version > 7:
      run("drush -l %s -y cr" % site)
    else:
      run("drush -l %s -y cc all" % site)


# @TODO: we should refactor the common.Services restart functions so they
# can handle receiving a host as an argument.

# Restart services
# yes, || exit 0 is weird, but apparently necessary as run()
# (or Jenkins) evaluates the possibility of running the 'false'
# action even if it's not going to return false.. stupid
def restart_services(orig_host):
  env.host_string = orig_host
  with settings(hide('warnings', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd', 'nginx', 'php-fpm', 'varnish']
    for service in services:
      print "===> Restarting %s if present" % service
      if service == 'php-fpm':
        if run("pgrep -lf %s | grep -v grep > /dev/null" % service).return_code == 0:
          run("sudo service php5-fpm restart")
      else:
        if run("pgrep -lf %s | grep -v grep > /dev/null" % service).return_code == 0:
          run("sudo service %s restart" % service)
