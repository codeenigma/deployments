from fabric.api import *
from fabric.contrib.files import exists
import os
import sys
import random
import string
import ConfigParser
# Custom Code Enigma modules
import common.ConfigFile
import common.Services
import common.Utils
import WordPress
import AdjustConfiguration
import InitialBuild
import Revert
# Needed to get variables set in modules back into the main script
from common.ConfigFile import *
from common.Utils import *
from WordPress import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
config = common.ConfigFile.read_config_file()


######
# New 'main()' task which should replace the deployment.sh wrapper, and support repo -> host mapping
#####
@task
def main(repo, repourl, build, branch, buildtype, url=None, keepbuilds=20, profile="minimal", webserverport='8080', php_ini_file=None):
  # We need to iterate through the options in the map and find the right host based on
  # whether the repo name matches any of the options, as they may not be exactly identical
  if config.has_section(buildtype):
    for option in config.options(buildtype):
       line = config.get(buildtype, option)
       line = line.split(',')
       for entry in line:
         if option.strip() in repo:
           env.host = entry.strip()
           print "===> Host is %s" % env.host
           break

  # Didn't find any host in the map for this project.
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Pick the user to SSH as
  user = "jenkins"

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Can be set in the config.ini [Build] section
  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")
  notifications_email = common.ConfigFile.return_config_item(config, "Build", "notifications_email")
  # Need to keep potentially passed in 'url' value as default
  url = common.ConfigFile.return_config_item(config, "Build", "url", "string", url)
  php_ini_file = common.ConfigFile.return_config_item(config, "Build", "php_ini_file", "string", php_ini_file)

  # Set a URL if one wasn't already provided
  if url is None:
    url = "%s-%s.codeenigma.net" % (repo, branch)

  cleanbranch = branch.replace('/', '-')

  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  with settings(warn_only=True):
    if exists('/var/www/live.%s.%s' % (repo, branch)):
      fresh_install = False
    else:
      fresh_install = True

  # Check the php_ini_file string isn't doing anything naughty
  malicious_code = False
  malicious_code = common.Utils.detect_malicious_strings([';', '&&'], php_ini_file)
  # Set CLI PHP version, if we need to
  if php_ini_file and not malicious_code:
    run("export PHPRC='%s'" % php_ini_file)

  if fresh_install == True:
    print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url
    try:
      common.Utils.clone_repo(repo, repourl, branch, build, None, ssh_key)
      InitialBuild.initial_build(repo, url, branch, build, profile, webserverport)
      # Unset CLI PHP version if we need to
      if php_ini_file:
        run("export PHPRC=''")
      common.Services.clear_php_cache()
      common.Services.clear_varnish_cache()
      common.Services.reload_webserver()
      print "####### BUILD COMPLETE. Your new WordPress site is available at %s" % (url)
    except:
      e = sys.exc_info()[1]
      raise SystemError(e)
  else:
    print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
    # Grab some information about the current build
    previous_build = common.Utils.get_previous_build(repo, cleanbranch, build)
    previous_db = common.Utils.get_previous_db(repo, cleanbranch, build)
    #cron_disable(repo, branch)
    WordPress.backup_db(repo, branch, build, previous_build)
    common.Utils.clone_repo(repo, repourl, branch, build, None, ssh_key)
    AdjustConfiguration.adjust_wp_config(repo, branch, build)
    AdjustConfiguration.adjust_files_symlink(repo, branch, build)
    #server_specific_tasks(repo, branch, build)
    WordPress.wp_status(repo, branch, build)
    #go_offline(repo, branch)
    WordPress.wp_updatedb(repo, branch, build)            # This will revert the database if it fails
    WordPress.wp_status(repo, branch, build, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

    try:
      common.Utils.adjust_live_symlink(repo, branch, build)
    except:
      # This will revert the database if fails
      Revert._revert_db(repo, branch, build)
      raise SystemExit("Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

    # Unset CLI PHP version if we need to
    if php_ini_file:
      run("export PHPRC=''")

    # Restart services
    common.Services.clear_php_cache()
    common.Services.clear_varnish_cache()

    # @TODO: cron generation not yet created
    #generate_wordpress_cron(repo, branch)

    common.Utils.remove_old_builds(repo, branch, keepbuilds)

    script_dir = os.path.dirname(os.path.realpath(__file__))
    if put(script_dir + '/../util/revert', '/home/jenkins', mode=0755).failed:
      print "####### BUILD COMPLETE. Could not copy the revert script to the application server, revert will need to be handled manually"
    else:
      print "####### BUILD COMPLETE. If you need to revert this build, run the following command: sudo /home/jenkins/revert -b %s -d %s -s /var/www/live.%s.%s -a %s_%s" % (previous_build, previous_db, repo, branch, repo, branch)

