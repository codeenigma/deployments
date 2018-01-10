from fabric.api import *
from fabric.contrib.files import sed
import random
import string
import time

# Small function to revert db
@task
def _revert_db(repo, branch, build):
  print "===> Dropping all tables"
  run("if [ -f ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz ]; then drush -y @%s_%s sql-drop; fi" % (repo, branch, build, repo, branch))
  print "===> Waiting 5 seconds to let MySQL internals catch up"
  time.sleep(5)
  print "===> Restoring the database from backup"
  run("if [ -f ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz ]; then zcat ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz | drush @%s_%s sql-cli; fi" % (repo, branch, build, repo, branch, build, repo, branch))

# Function to revert settings.php change for when a build fails and database is reverted
@task
def _revert_settings(repo, branch, build):
  with settings(warn_only=True):
    settings_file = "/var/www/config/%s_%s.settings.inc" % (repo, branch)
    stable_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    replace_string = "/var/www/.*\.settings\.php"
    replace_with = "%s/www/sites/default/%s.settings.php" % (stable_build, branch)
    sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='', flags="i", shell=True)
    print "===> Reverted settings.php"

