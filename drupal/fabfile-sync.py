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
def main(shortname, staging_branch, prod_branch, synctype='both', fresh_database='no', sanitise='yes', sanitised_password='kiloh6Ca'):
  # Set the variables we need.
  drupal_version = None
  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  with settings(warn_only=True):
    if run('drush sa | grep ^@%s_%s$ > /dev/null' % (shortname, staging_branch)).failed:
      raise SystemError("You can't sync to a site if it hasn't been set up yet in this environment.")
    else:
      print "===> We found the site, so we'll continue with the sync"
      path_to_drupal = run("drush @%s_%s st --fields=root | grep -oEi '\/var\/www\/%s_%s_build_[0-9]+' | sed 's/ //g'" % (shortname, staging_branch, shortname, staging_branch))
      print "===> Path is %s" % path_to_drupal

      path_to_config_file = path_to_drupal + '/config.ini'

      drupal_config = common.ConfigFile.read_config_file(path_to_config_file, False, True, True)

    if config.has_section(shortname):
      try:
        orig_host = "%s@%s" % (env.user, env.host)

        # Get Drupal version
        drupal_version = DrupalUtils.determine_drupal_version(drupal_version, shortname, staging_branch, 0, drupal_config, 'sync')

        # Allow developer to run a script prior to a sync
        common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'pre')

        # Database syncing
        if synctype == 'db' or synctype == 'both':
          Sync.backup_db(shortname, staging_branch)
          Sync.sync_db(orig_host, shortname, staging_branch, prod_branch, fresh_database, sanitise, sanitised_password, config)
          Sync.drush_updatedb(orig_host, shortname, staging_branch)

        # Files syncing (uploads)
        if synctype == 'files' or synctype == 'both':
          Sync.sync_assets(orig_host, shortname, staging_branch, prod_branch, config)

        # Cleanup
        Sync.clear_caches(orig_host, shortname, staging_branch, drupal_version)
        # @TODO: Ask Emlyn about this, why do we uninstall memcached for LBHF?
        # Make this a hook?
        #server_specific_tasks(orig_host, shortname, staging_branch)
        env.host_string = orig_host
        common.Services.clear_php_cache()
        common.Services.clear_varnish_cache()
        common.Services.reload_webserver()
        #Sync.restart_services(orig_host)
        # Allow developer to run a script after a sync
        common.Utils.perform_client_sync_hook(path_to_drupal, staging_branch, 'post')

      except:
        e = sys.exc_info()[1]
        raise SystemError(e)
    else:
      raise SystemError("Could not find this shortname %s in the sync.ini so we cannot proceed." % shortname)
