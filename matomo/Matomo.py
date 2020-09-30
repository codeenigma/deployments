from fabric.api import *
import Revert

# Take a database backup
@task
@roles('app_primary')
def mysql_backup_db(db_name, build, fail_build=False, mysql_config='/etc/mysql/debian.cnf'):
  print "===> Ensuring backup directory exists"
  with settings(warn_only=True):
    if sudo("mkdir -p /var/www/shared/dbbackups").failed:
      raise SystemExit("######### Could not create directory /var/www/shared/dbbackups! Aborting early")
  print "===> Taking a database backup..."
  sudo("chown jenkins:jenkins /var/www/shared/dbbackups")
  sudo("chmod 700 /var/www/shared/dbbackups")
  with settings(warn_only=True):
    if sudo("mysqldump --defaults-file=%s %s | gzip > /var/www/shared/dbbackups/%s_prior_to_%s.sql.gz; if [ ${PIPESTATUS[0]} -ne 0 ]; then exit 1; else exit 0; fi" % (mysql_config, db_name, db_name, build)).failed:
      failed_backup = True
    else:
      failed_backup = False

  if failed_backup and fail_build:
    raise SystemExit("######### Could not take database backup prior to launching new build! Aborting early")
  if failed_backup:
    print "######### Backup failed, but build set to continue regardless"


# Run database updates
@task
@roles('app_primary')
def database_updates(repo, branch, build, www_root, application_directory, db_name):
  print "Applying database updates."
  with settings(warn_only=True):
    with cd("%s/%s_%s_%s/%s" % (www_root, repo, branch, application_directory)):
      if run("su -s /bin/bash www-data -c 'console core:update'").failed:
        print "Could not run database updates. Reverting database and aborting."
        execute(Revert._revert_db, repo, branch, build, db_name)


# Clear Matomo cache
@task
@roles('app_primary')
def clear_cache(repo, branch, build, www_root, application_directory):
  print "Clearing cache."
  with settings(warn_only=True):
    with cd("%s/%s_%s_%s/%s" % (www_root, repo, branch, application_directory)):
      if run("su -s /bin/bash www-data -c 'console cache:clear'").failed:
        print "Could not clear the cache. Not failing the build though."


