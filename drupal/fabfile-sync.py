from fabric.api import *
from fabric.contrib.files import *
import os
import sys
import random
import string
import ConfigParser
# Custom Code Enigma modules
import common.ConfigFile
import common.Services
import common.Utils
import DrupalUtils
import Sync

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
global config
config = common.ConfigFile.read_config_file('sync.ini', False)

@task
def main(shortname, staging_branch, prod_branch, synctype='both', fresh_database='no', sanitise='yes', sanitised_password=None, sanitised_email=None, staging_shortname=None, remote_files_dir=None, staging_files_dir=None, sync_dir=None):
  # Set the variables we need.
  drupal_version = None
  app_dir = "www"
  # If we didn't get a staging shortname, we should set it to shortname
  if staging_shortname is None:
    staging_shortname = shortname
  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  with settings(warn_only=True):
    site_exists = common.Utils.get_previous_build(staging_shortname, staging_branch, 0)
    if site_exists is None:
      raise SystemError("You can't sync to a site if it hasn't been set up yet in this environment.")
    else:
      print "===> We found the site, so we'll continue with the sync"
      path_to_drupal = site_exists
      print "===> Path is %s" % path_to_drupal

      path_to_config_file = path_to_drupal + '/config.ini'

      drupal_config = common.ConfigFile.read_config_file(path_to_config_file, False, True, True)

  if config.has_section(shortname):
    try:
      orig_host = "%s@%s" % (env.user, env.host)

      # Get Drupal version
      ### @TODO: deprecated, can be removed later
      drupal_version = common.ConfigFile.return_config_item(config, "Version", "drupal_version", "string", None, True, True, replacement_section="Drupal")
      # This is the correct location for 'drupal_version' - note, respect the deprecated value as default
      drupal_version = common.ConfigFile.return_config_item(config, "Drupal", "drupal_version", "string", drupal_version)
      drupal_version = int(DrupalUtils.determine_drupal_version(drupal_version, shortname, staging_branch, 0, drupal_config, 'sync'))

      # Allow developer to run a script prior to a sync
      common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'pre')

      stage_drupal_root = path_to_drupal + '/' + app_dir

      # Database syncing
      if synctype == 'db' or synctype == 'both':
        Sync.backup_db(staging_shortname, staging_branch, stage_drupal_root)
        Sync.sync_db(orig_host, shortname, staging_shortname, staging_branch, prod_branch, fresh_database, sanitise, sanitised_password, sanitised_email, config, drupal_version, stage_drupal_root, app_dir)
        # Allow developer to run a script mid-way through a sync
        common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'mid-db')
        Sync.drush_updatedb(orig_host, staging_shortname, staging_branch, stage_drupal_root)

      # Files syncing (uploads)
      if synctype == 'files' or synctype == 'both':
        Sync.sync_assets(orig_host, shortname, staging_shortname, staging_branch, prod_branch, config, app_dir, remote_files_dir, staging_files_dir, sync_dir)
        # Allow developer to run a script mid-way through a sync
        common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'mid-files')

      # Cleanup
      Sync.clear_caches(orig_host, staging_shortname, staging_branch, drupal_version, stage_drupal_root)
      env.host_string = orig_host
      common.Services.clear_php_cache()
      common.Services.clear_varnish_cache()
      common.Services.reload_webserver()
      # Allow developer to run a script after a sync
      common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'post')

    except:
      e = sys.exc_info()[1]
      raise SystemError(e)
  else:
    raise SystemError("Could not find this shortname %s in the sync.ini so we cannot proceed." % staging_shortname)
