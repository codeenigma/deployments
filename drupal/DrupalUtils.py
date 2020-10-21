from fabric.api import *
import common.ConfigFile


# Runs a drush command
@task
def drush_command(drush_command, drush_site=None, drush_runtime_location=None, drush_sudo=False, drush_format=None, drush_path=None, www_user=False):
  this_command = ""
  # Allow calling applications to specify a path to drush
  if drush_path:
    this_command = this_command + drush_path + " -y "
  else:
    this_command = this_command + "drush -y "
  # Set an optional format for the output
  if drush_format:
    this_command = this_command + "--format=%s " % drush_format
  # Pass a URI to drush to process a multisite
  if drush_site:
    this_command = this_command + "-l " + drush_site
  # Build the final command
  this_command = this_command + " " + drush_command
  # Optionally set a runtime location
  if drush_runtime_location:
    this_command = "cd %s && %s" % (drush_runtime_location, this_command)
  # Optionally run as the web user - this needs to be last to wrap the whole thing
  if www_user:
    this_command = "su -s /bin/bash www-data -c '" + this_command + "'"
  # Report back before executing
  print "===> Running the following command for drush:"
  print "=====> %s" % this_command
  drush_output = ""
  if drush_sudo:
    drush_output = sudo(this_command)
  else:
    drush_output = run(this_command)
  # Send back whatever happened in case another script needs it
  return drush_output


# Determine which Drupal version is being used
@task
def determine_drupal_version(drupal_version, repo, branch, build, config, method="deployment"):
  # If this is a normal deployment (deployment), use the build number path. If this is a sync (sync), use the live symlink path.
  if method == "sync":
    drupal_path = "/var/www/live.%s.%s" % (repo, branch)
  else:
    drupal_path = "/var/www/%s_%s_%s" % (repo, branch, build)

  # If no version specified, we'll have to detect it
  if drupal_version is None:
    print "===> No drupal_version override in config.ini, so we'll figure out the version of Drupal ourselves"

    drush_runtime_location = "%s/www" % drupal_path
    # We're only checking the Drupal version so it's fine to not pass a 'site' and rely on default
    drush_output = drush_command("status", None, drush_runtime_location, False, "yaml")
    if run("echo \"%s\" | grep 'drupal-version'" % drush_output).failed:
      raise SystemExit("####### Could not determine Drupal version from drush st. If you're using composer, you MUST override this check in the config.ini file with drupal_version set in the [Drupal] section. Please raise a ticket if you're not sure how to do this.")
    else:
      drupal_version = run("echo \"%s\" | grep \"drupal-version\" | cut -d\: -f2 | cut -d. -f1" % drush_output)
      drupal_version = drupal_version.strip()
      # Older versions of Drupal put version in single quotes
      drupal_version = drupal_version.strip("'")

  print "===> Drupal version is Drupal %s." % drupal_version
  return drupal_version


# Fetch a fresh database dump from target server
@task
def get_database(shortname, branch, sanitise, site="default"):
  # First, check the site exists on target server server
  if run("readlink /var/www/live.%s.%s" % (shortname, branch)).failed:
    raise SystemError("####### ERROR: Could not find a site at /var/www/live.%s.%s in order to grab a database dump. Aborting." % (shortname, branch))

  print "===> Found a site at /var/www/live.%s.%s. Let's grab a database and copy it down." % (shortname, branch)

  # Make sure a backup directory exists
  print "===> Make sure a backup directory exists on target server..."
  run("mkdir -p ~jenkins/client-db-dumps")

  # Let's dump the database into a bzip2 file
  print "===> Dumping database into bzip2 file..."
  if sanitise == "yes":
    # We need to run a special mysqldump command to obfustcate the database
    with settings(hide('running', 'stdout', 'stderr')):

      with cd("/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)):
        db_name_output = sudo("grep -v \"*\" settings.php | grep \"'database' => '%s*\" | cut -d \">\" -f 2" % repo)
        db_user_output = sudo("grep -v \"*\" settings.php | grep \"'username' => \" | cut -d \">\" -f 2" )
        db_pass_output = sudo("grep -v \"*\" settings.php | grep \"'password' => \" | cut -d \">\" -f 2" )
        db_host_output = sudo("grep -v \"*\" settings.php | grep \"'host' => \" | cut -d \">\" -f 2" )

      db_name = db_name_output.translate(None, "',")
      db_user = db_user_output.translate(None, "',")
      db_pass = db_pass_output.translate(None, "',")
      db_host = db_host_output.translate(None, "',")

      run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /usr/local/bin/drupal-obfuscate.rb | bzip2 -f > ~jenkins/client-db-dumps/%s-%s_database_dump.sql.bz2' % (dbuser, dbpass, dbhost, dbname, shortname, branch))

  else:
    run('cd /var/www/live.%s.%s/www/sites/%s && drush -l %s -y sql-dump | bzip2 -f > ~jenkins/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch, site, site, shortname, branch))

  # Make sure a directory exists for database dumps to be downloaded to
  local('mkdir -p /tmp/client-db-dumps')

  # Now fetch it from target server
  print "===> Fetching database from target server..."
  get('~/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch), '/tmp/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch))

  # Remove database dump from target server
  print "===> Removing database dump from target server..."
  run('rm ~/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch))


@task
def check_site_exists(previous_build, site):
  if previous_build is None:
    print "###### No live symlink at all, so this is a totally new initial build."
    return False
  else:
    with settings(warn_only=True):
      if run("stat %s/www/sites/%s/settings.php" % (previous_build, site)).return_code == 0:
        print "###### %s site exists." % site
        return True
      else:
        print "###### %s site does not exist." % site
        return False
