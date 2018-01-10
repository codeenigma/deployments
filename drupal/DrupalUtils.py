from fabric.api import *
import common.ConfigFile


# Determine which Drupal version is being used
@task
def determine_drupal_version(drupal_version, repo, branch, build, config, method="deployment"):
  # If this is a normal deployment (deployment), use the build number path. If this is a sync (sync), use the live symlink path.
  if method == "sync":
    drupal_path = "/var/www/live.%s.%s" % (repo, branch)
  else:
    drupal_path = "/var/www/%s_%s_%s" % (repo, branch, build)

  # Check to see if Drupal version is specified in config file
  if config.has_section("Drupal"):
    print "===> Fetching version from config.ini"
    if config.has_option("Drupal", "drupal_version"):
      drupal_version = config.get("Drupal", "drupal_version")

  # If no version specified, we'll have to detect it
  if drupal_version is None:
    print "===> No drupal_version override in config.ini, so we'll figure out the version of Drupal ourselves"

    if run("cd %s/www && drush st | grep 'Drupal version'" % drupal_path).failed:
      raise SystemExit("Could not determine Drupal version from drush st. If you're using composer, you MUST override this check in the config.ini file with drupal_version set in the [Drupal] section. Please raise a ticket if you're not sure how to do this.")
    else:
      drupal_version = run("cd %s/www && drush st | grep \"Drupal version\" | cut -d\: -f2 | cut -d. -f1" % drupal_path)
      drupal_version = drupal_version.strip()

  print "===> Drupal version is D%s." % drupal_version
  return drupal_version


# Fetch a fresh database dump from target server
@task
def get_database(shortname, branch, santise):
  # First, check the site exists on target server server
  if run('drush sa | grep ^@%s_%s$ > /dev/null' % (shortname, branch)).failed:
    print "ERROR: Could not find a site with the Drush alias %s_%s in order to grab a database dump. Aborting." % (shortname, branch)
    raise SystemError("Could not find a site with the Drush alias %s_%s in order to grab a database dump. Aborting." % (shortname, branch))

  print "===> Found a site with Drush alias %s_%s. Let's grab a database and copy it down." % (shortname, branch)

  # Make sure a backup directory exists
  print "===> Make sure a backup directory exists on target server..."
  run("mkdir -p ~jenkins/client-db-dumps")

  # Let's dump the database into a bzip2 file
  print "===> Dumping database into bzip2 file..."
  if santise == "yes":
    # @TODO: this will need Drupal 8 support!
    # We need to run a special mysqldump command to obfustcate the database
    with settings(hide('running', 'stdout', 'stderr')):
      dbname = run("drush @%s_%s status  Database\ name | awk {'print $4'} | head -1" % (shortname, branch))
      dbuser = run("drush @%s_%s status  Database\ user | awk {'print $4'} | head -1" % (shortname, branch))
      dbpass = run("drush @%s_%s --show-passwords status  Database\ pass | awk {'print $4'} | head -1" % (shortname, branch))
      dbhost = run("drush @%s_%s status  Database\ host | awk {'print $4'} | head -1" % (shortname, branch))
      run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /usr/local/bin/drupal-obfuscate.rb | bzip2 -f > ~jenkins/client-db-dumps/%s-%s_database_dump.sql.bz2' % (dbuser, dbpass, dbhost, dbname, shortname, branch))
  else:
    run('drush @%s_%s sql-dump | bzip2 -f > ~jenkins/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch, shortname, branch))

  # Make sure a directory exists for database dumps to be downloaded to
  local('mkdir -p /tmp/client-db-dumps')

  # Now fetch it from target server
  print "===> Fetching database from target server..."
  get('~/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch), '/tmp/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch))

  # Remove database dump from target server
  print "===> Removing database dump from target server..."
  run('rm ~/client-db-dumps/%s-%s_database_dump.sql.bz2' % (shortname, branch))
