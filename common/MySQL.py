from fabric.api import *
from fabric.operations import put
from fabric.contrib.files import *
import random
import string
import time
# Custom Code Enigma modules
import common.Utils


# Create a new database
@task
@roles('app_primary')
def mysql_new_database(repo, buildtype, rds=False, db_name=None, db_host=None, db_username=None, mysql_version=5.5, db_password=None, mysql_config='/etc/mysql/debian.cnf', app_hosts=None, dump_file=None):
  # Set default hosts
  if db_host is None:
    db_host = "localhost"
  if app_hosts is None:
    app_hosts = [ 'localhost' ]
  # Make our DB server the active host for Fabric
  # Note, for localhost or for 'rds' this is not desired
  if not db_host == "localhost" or rds:
    original_host = env.host
    env.host = db_host

  # Set database password
  if db_password is None:
    db_password = common.Utils._gen_passwd()
  # Make sure provided password is not longer than the permitted 41 characters
  db_password = (db_password[:41]) if len(db_password) > 41 else db_password
  print "===> Database password will be %s" % db_password

  # Different MySQL versions support different string lengths for database and user name
  # Set safe defaults for MySQL 5.5 or lower
  db_name_length = 16
  db_username_length = 16
  # Make sure mysql_version is a float
  mysql_version = float(mysql_version)
  # If MySQL version is 5.6 or higher, allow longer names
  if mysql_version > 5.6:
    db_name_length = 64
    db_username_length = 32
  elif mysql_version == 5.6:
    db_name_length = 32
  # Allow space for integer suffix if required
  db_name_length = db_name_length - 4
  print "===> MySQL version is %s, setting database name length to %s and username length to %s." % (mysql_version, db_name_length, db_username_length)

  # Set database name to repo_buildtype if none provided
  if db_name is None:
    db_name = repo + '_' + buildtype
  # Truncate the database name if necessary
  db_name = (db_name[:db_name_length]) if len(db_name) > db_name_length else db_name
  print "===> Database name will be %s." % db_name

  # Now let's set up the database
  database_created = False
  counter = 0
  original_db_name = db_name
  while not database_created:
    with settings(warn_only=True):
      if db_name == sudo("mysql --defaults-file=%s -Bse 'show databases' | egrep \"^%s$\"" % (mysql_config, db_name)):
        print "===> The database %s already exists." % db_name
        counter += 1
        db_name = original_db_name + '_' + str(counter)
      else:
        # Use the database name as username if none provided
        if db_username is None:
          db_username = db_name
        # Truncate the database username if necessary
        db_username = (db_username[:db_username_length]) if len(db_username) > db_username_length else db_username

        print "===> Database username will be %s." % db_username
        print "===> Creating database %s." % db_name
        sudo("mysql --defaults-file=%s -e 'CREATE DATABASE `%s`'" % (mysql_config, db_name))
        # Set MySQL grants for each app server
        for host in app_hosts:
          print "===> Creating a grant host %s." % host
          sudo("mysql --defaults-file=%s -e 'GRANT ALL ON `%s`.* TO \"%s\"@\"%s\" IDENTIFIED BY \"%s\"'" % (mysql_config, db_name, db_username, host, db_password))
        print "===> Flush privileges."
        sudo("mysql --defaults-file=%s -e 'FLUSH PRIVILEGES'" % mysql_config)
        # We're done here, break out of the loop
        database_created = True

  # Put the correct host back for Fabric to continue
  if not db_host == "localhost" or rds:
    env.host = original_host

  # We might need the database details back for later
  return [ db_name, db_username, db_password, db_host ]


# Import a seed database
@task
@roles('app_primary')
def mysql_import_dump(site_root, db_name, dump_file, db_host=None, rds=False, mysql_config='/etc/mysql/debian.cnf'):
  # Set default db host
  if db_host is None:
    db_host = "localhost"
  # Make our DB server the active host for Fabric
  # Note, for localhost or for 'rds' this is not desired
  if not db_host == "localhost" or rds:
    original_host = env.host
    env.host = db_host

  dump_file = site_root + '/db/' + dump_file
  print "===> Importing a database dump from %s into %s." % (dump_file, db_name)
  if exists(dump_file):
    extension = dump_file[-3:]
    if extension == 'sql':
      sudo("mysql --defaults-file=%s %s < %s" % (mysql_config, db_name, dump_file))
    elif extension == '.gz' or extension == 'zip':
      sudo("zcat %s | mysql --defaults-file=%s %s" % (dump_file, mysql_config, db_name))
    elif extension == 'bz2':
      sudo("bzcat %s | mysql --defaults-file=%s %s" % (dump_file, mysql_config, db_name))
    else:
      SystemExit("###### Don't recognise the format of this database dump, assuming it's critical and aborting!")
  else:
    SystemExit("###### The database dump file provided does not exist, assuming it's critical and aborting!")

  # Put the correct host back for Fabric to continue
  if not db_host == "localhost" or rds:
    env.host = original_host


# Take a database backup
@task
@roles('app_primary')
def mysql_backup_db(db_name, build, fail_build=False, mysql_config='/etc/mysql/debian.cnf'):
  print "===> Ensuring backup directory exists"
  with settings(warn_only=True):
    if run("mkdir -p ~jenkins/dbbackups").failed:
      raise SystemExit("######### Could not create directory ~jenkins/dbbackups! Aborting early")
  print "===> Taking a database backup..."
  with settings(warn_only=True):
    if sudo("mysqldump --defaults-file=%s %s | gzip > ~jenkins/dbbackups/%s_prior_to_%s.sql.gz; if [ ${PIPESTATUS[0]} -ne 0 ]; then exit 1; else exit 0; fi" % (mysql_config, db_name, db_name, build)).failed:
      failed_backup = True
    else:
      failed_backup = False

  if failed_backup and fail_build:
    raise SystemExit("######### Could not take database backup prior to launching new build! Aborting early")
  if failed_backup:
    print "######### Backup failed, but build set to continue regardless"


# Revert a MySQL database to a previously taken backup
@task
def mysql_revert_db(db_name, build, mysql_config='/etc/mysql/debian.cnf'):
  print "===> Dropping all tables"
  sudo("if [ -f ~jenkins/dbbackups/%s_prior_to_%s.sql.gz ]; then mysql --defaults-file=%s -e 'drop database `%s`'; fi" % (db_name, build, mysql_config, db_name))
  sudo("mysql --defaults-file=%s -e 'create database `%s`'" % (mysql_config, db_name))
  print "===> Waiting 5 seconds to let MySQL internals catch up"
  time.sleep(5)
  print "===> Restoring the database from backup"
  sudo("if [ -f ~jenkins/dbbackups/%s_prior_to_%s.sql.gz ]; then zcat ~jenkins/dbbackups/%s_prior_to_%s.sql.gz | mysql --defaults-file=%s -D %s; fi" % (db_name, build, db_name, build, mysql_config, db_name))
