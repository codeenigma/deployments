from fabric.api import *
import common.ConfigFile
import re


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

      with cd("/var/www/live.%s.%s/www/sites/%s" % (shortname, branch, site)):
        db_name_output = sudo("grep -v \"*\" settings.php | grep \"'database' => '%s*\" | cut -d \">\" -f 2" % shortname)
        db_user_output = sudo("grep -v \"*\" settings.php | grep \"'username' => \" | cut -d \">\" -f 2" )
        db_pass_output = sudo("grep -v \"*\" settings.php | grep \"'password' => \" | cut -d \">\" -f 2" )
        db_host_output = sudo("grep -v \"*\" settings.php | grep \"'host' => \" | cut -d \">\" -f 2" )

      db_name = db_name_output.translate(None, "',")
      db_user = db_user_output.translate(None, "',")
      db_pass = db_pass_output.translate(None, "',")
      db_host = db_host_output.translate(None, "',")

      run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /usr/local/bin/drupal-obfuscate.rb | bzip2 -f > ~jenkins/client-db-dumps/%s-%s_database_dump.sql.bz2' % (db_user, db_pass, db_host, db_name, shortname, branch))

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

@task
def determine_drush_major_version(drush_path=None):
  """
  Find the Drush version (major)

  The output of drush --version can be any of the following:
  - Drush Commandline Tool 10.3.5
  - Drush Commandline Tool 9.7.2
  - Drush Version   :  8.4.5
  - Drush Version   :  7.4.0
  and can include warnings...

  I've used a modified version of the semver regex: I removed ^ from the
  beginning and $ from the end so that wherever the version appears in the
  string, it'll hopefully find it

  @see https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
  """
  drush_version_output = run(drush_path + " --version") if drush_path else run("drush --version")
  semver = re.compile("(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?")
  drush_version = semver.search(drush_version_output)

  if drush_version:
    return int(drush_version.group('major'))
  raise SystemExit("Unable to determine the installed version of Drush")

@task
def update_user_password(name, password):
  """
  Update the password of the named user using Drush

  Prior to Drush 9.x, the upwd command expected --password, newer versions of
  Drush do not.
  """
  if determine_drush_major_version() >= 9:
    return drush_command("upwd %s '%s'" % (name, password))
  return drush_command("upwd %s --password='%s'" % (name, password))
