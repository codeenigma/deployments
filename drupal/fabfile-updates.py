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
import Drupal
import AdjustConfiguration
import InitialBuild
import Revert
import Tests
import Updates
# Needed to get variables set in modules back into the main script
from Tests import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
config = common.ConfigFile.read_config_file()


######
# New 'main()' task which should replace the deployment.sh wrapper, and support repo -> host mapping
#####
@task
def main(repo, repourl, build, branch, buildtype, url=None, profile="minimal", readonlymode=""):
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

  user = "jenkins"

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Set SSH key if needed
  ssh_key = None
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

  # Set a URL if one wasn't already provided
  if url is None:
    url = "%s.%s.%s" % (repo, branch, env.host)

  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  with settings(warn_only=True):
    if run('drush sa | grep \'^@\?%s_%s$\' > /dev/null' % (repo, branch)).failed:
      fresh_install = True
    else:
      fresh_install = False

  if fresh_install == True:
    print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url
    try:
      common.Utils.clone_repo(repo, repourl, branch, build, None, ssh_key)
      InitialBuild.initial_build(repo, url, branch, build, profile)
      AdjustConfiguration.adjust_drushrc_php(repo, branch, build)
      common.Services.clear_php_cache()
      common.Services.clear_varnish_cache()
      common.Services.reload_webserver()
      InitialBuild.generate_drush_alias(repo, url, branch)
      Drupal.generate_drush_cron(repo, branch)
    except:
      e = sys.exc_info()[1]
      raise SystemError(e)
  else:
    print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
    # Grab some information about the current build
    previous_build = common.Utils.get_previous_build(repo, cleanbranch, build)
    previous_db = common.Utils.get_previous_db(repo, cleanbranch, build)

    Drupal.backup_db(repo, branch, build)
    common.Utils.clone_repo(repo, repourl, branch, build, None, ssh_key)
    Updates.merge_prod(repo, branch, build)
    AdjustConfiguration.adjust_settings_php(repo, branch, build, previous_build, buildtype)
    AdjustConfiguration.adjust_drushrc_php(repo, branch, build)
    AdjustConfiguration.adjust_files_symlink(repo, branch, build)
    Drupal.drush_status(repo, branch, build)
    Drupal.go_offline(repo, branch, build, readonlymode)
# No need for this, drush_up does it later
#    drush_updatedb(repo, branch, build)            # This will revert the database if it fails
    common.Utils.adjust_live_symlink(repo, branch, build)       # This will revert the database if it fails
    Updates.drush_up(repo, branch)
    Drupal.drush_status(repo, branch, build, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)
    Updates.add_push_updates(repo, branch, build)
    Drupal.go_online(repo, branch, build, previous_build, readonlymode) # This will revert the database and switch the symlink back if it fails
    common.Services.clear_php_cache()
    common.Services.clear_varnish_cache()
    Drupal.generate_drush_cron(repo, branch)
    Tests.run_tests(repo, branch, build)
    #run_behat_tests(repo, branch, build)
    #commit_new_db(repo, repourl, url, build, branch)
    common.Utils.remove_old_builds(repo, branch)
    Updates.send_update_notification(repo, branch)

    script_dir = os.path.dirname(os.path.realpath(__file__))
    if put(script_dir + '/../util/revert', '/home/jenkins', mode=0755).failed:
      print "####### BUILD COMPLETE. Could not copy the revert script to the application server, revert will need to be handled manually"
    else:
      print "####### BUILD COMPLETE. If you need to revert this build, run the following command: sudo /home/jenkins/revert -b %s -d %s -s /var/www/live.%s.%s -a %s_%s" % (previous_build, previous_db, repo, branch, repo, branch)
