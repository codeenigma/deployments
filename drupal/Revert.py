from fabric.api import *
from fabric.contrib.files import sed
import random
import string
import time
# Custom Code Enigma modules
import Drupal
import common.MySQL


# Small function to revert db
@task
@roles('app_primary')
def _revert_db(repo, branch, build, buildtype, site):
  print "===> Reverting the database..."
  drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)
  drush_output = Drupal.drush_status(repo, branch, build, buildtype, site, drush_runtime_location)
  db_name = Drupal.get_db_name(repo, branch, build, buildtype, site, drush_output)
  common.MySQL.mysql_revert_db(db_name, build)

# Function to revert settings.php change for when a build fails and database is reverted
@task
@roles('app_all')
def _revert_settings(repo, branch, build, buildtype, site, alias):
  print "===> Reverting the settings..."
  with settings(warn_only=True):
    settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
    stable_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    replace_string = "/var/www/.*\.settings\.php"
    replace_with = "%s/www/sites/%s/%s.settings.php" % (stable_build, site, buildtype)
    sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='', flags="i", shell=True)
    print "===> Reverted settings.php"

