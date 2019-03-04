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
  print "===> Reverting the database for %s site..." % site
  drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)
  drush_output = Drupal.drush_status(repo, branch, build, buildtype, site, drush_runtime_location)
  db_name = Drupal.get_db_name(repo, branch, build, buildtype, site, drush_output)

  # Get Drupal version to pass to cache clear and _revert_go_online()
  drupal_version = run("echo \"%s\" | grep \"drupal-version\" | cut -d\: -f2 | cut -d. -f1" % drush_output)
  drupal_version = drupal_version.strip()
  # Older versions of Drupal put version in single quotes
  drupal_version = drupal_version.strip("'")

  common.MySQL.mysql_revert_db(db_name, build)
  Drupal.drush_clear_cache(repo, branch, build, site, drupal_version)
  _revert_go_online(repo, branch, build, site, drupal_version)


# Function to revert settings.php change for when a build fails and database is reverted
@task
@roles('app_all')
def _revert_settings(repo, branch, build, buildtype, site, alias):
  print "===> Reverting settings.php for %s site..." % site
  with settings(warn_only=True):
    settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
    stable_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    if sudo('sed -i.bak "s:/var/www/.*\.settings\.php:%s/www/sites/%s/%s.settings.php:g" %s' % (stable_build, site, buildtype, settings_file)).failed:
      print "===> Could not revert settings.php. Manual intervention required."
    else:
      print "===> Reverted settings.php"


# Function to put the site back online after a revert, as the site would have been put into maintenance mode *before* the backup was taken
@task
@roles('app_primary')
def _revert_go_online(repo, branch, build, site, drupal_version=None):
  print "===> Bringing the %s site back online." % site

  drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)

  with settings(warn_only=True):
    if drupal_version is None:
      drush_output = Drupal.drush_status(repo, branch, build, buildtype, site, drush_runtime_location)

      # Get Drupal version to pass to cache clear and _revert_go_online()
      drupal_version = run("echo \"%s\" | grep \"drupal-version\" | cut -d\: -f2 | cut -d. -f1" % drush_output)
      drupal_version = drupal_version.strip()
      # Older versions of Drupal put version in single quotes
      drupal_version = drupal_version.strip("'")

    if drupal_version > 7:
      online_command = "state-set system.maintenance_mode 0"
    else:
      online_command = "vset site_offline 0"

    DrupalUtils.drush_command(online_command, site, drush_runtime_location)
    Drupal.drush_clear_cache(repo, branch, build, site, drupal_version)
