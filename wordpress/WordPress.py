from fabric.api import *
from fabric.contrib.files import *
import random
import string
# Custom Code Enigma modules
import common.Services
import Revert


# Take a database backup
@task
def backup_db(repo, branch, build, previous_build):
  print "===> Ensuring backup directory exists"
  with settings(warn_only=True):
    if run("mkdir -p ~jenkins/dbbackups").failed:
      raise SystemExit("Could not create directory ~jenkins/dbbackups! Aborting early")

  print "===> Taking a database backup..."

  with settings(warn_only=True):
    # There is a --tables=table1,table2 option available and you can pass arguments to mysqldump directly - see wp-cli help
    if run("wp --allow-root --path=%s/www db export - | gzip > ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz; if [ ${PIPESTATUS[0]} -ne 0 ]; then exit 1; else exit 0; fi" % (previous_build, repo, branch, build)).failed:
      failed_backup = True
    else:
      failed_backup = False

  if failed_backup:
    raise SystemExit("Could not take database backup prior to launching new build! Aborting early")
  
  
 # Run a wp-cli is-installed check against that build
@task
def wp_status(repo, branch, build, revert=False):
  print "===> Running a wp-cli core is-installed test"
  with cd("/var/www/%s_%s_%s/www" % (repo, branch, build)):
    with settings(warn_only=True):
      if run("wp --allow-root core is-installed").failed:
        if revert == True:
          print "Reverting the database..."
          Revert._revert_db(repo, branch, build)
        raise SystemExit("Could not bootstrap the database on this build! Aborting")


# Run drush updatedb to apply any database changes from hook_update's
@task
def wp_updatedb(repo, branch, build):
  print "===> Running any database hook updates"
  with settings(warn_only=True):
    # Apparently APC cache can interfere with database updates
    common.Services.clear_php_cache()
    common.Services.clear_varnish_cache()
    if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www && wp --allow-root core update-db'" % (repo, branch, build)).failed:
      print "Could not apply database updates! Reverting this database"
      Revert._revert_db(repo, branch, build)
      raise SystemExit("Could not apply database updates! Reverted database. Site remains on previous build")
    else:
      sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www && wp --allow-root cache flush'" % (repo, branch, build))


# Greg: This is drush stuff that needs replacing with http://wp-cli.org/
#
# Take a database backup and send it back into the repo
# Currently this is not active (it starts a build loop
# since it invokes an SCM change in Jenkins)
#@task
#def commit_new_db(repo, branch, build):
#  print "===> Committing the latest db back to the repo"
  # We need to create the dbbackups branch and push it in case it doesn't already exist
#  _sshagent_run("cd /var/www/%s_%s_%s && git branch -f dbbackups && git push origin dbbackups" % (repo, branch, build))
  # If it *did* already exist, we need to pull the latest changes or else we'll get a conflict if we do this after we make a new dump
#  _sshagent_run("cd /var/www/%s_%s_%s && git pull origin dbbackups" % (repo, branch, build))
#  run("drush @%s_%s sql-dump --result-file=/dev/stdout | bzip2 -f > /var/www/%s_%s_%s/db/%s.%s.sql.bz2" % (repo, branch, repo, branch, build, repo, branch))
#  with cd("/var/www/live.%s.%s" % (repo, branch)):
#    run("git add db/%s.%s.sql.bz2" % (repo, branch))
#    run("git commit -m \"New database dump taken after successful %s build %s\"" % (branch, build))
#    run("git branch -f dbbackups")
#  _sshagent_run("cd /var/www/live.%s.%s && git push origin dbbackups" % (repo, branch))
