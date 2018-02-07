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
import DrupalTests
import DrupalUtils
import Multisite
import FeatureBranches
# Needed to get variables set in modules back into the main script
from DrupalTests import *
from FeatureBranches import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
global config
config = common.ConfigFile.read_config_file()


######
# New 'main()' task which should replace the deployment.sh wrapper, and support repo -> host mapping
#####
@task
def main(repo, repourl, build, branch, buildtype, url=None, profile="minimal", keepbuilds=10, runcron="False", doupdates="yes", freshdatabase="Yes", syncbranch=None, sanitise="no", statuscakeuser=None, statuscakekey=None, statuscakeid=None, importconfig="yes", restartvarnish="yes", cluster=False, webserverport='8080', rds=False, composer=True, no_dev=True):
  dontbuild = False

  # Define variables
  drupal_version = None
  user = "jenkins"
  mapping = {}

  global varnish_restart
  varnish_restart = restartvarnish
  readonlymode = "maintenance"
  fra = False
  config_export = False
  previous_build = ""
  previous_db = ""
  statuscake_paused = False
  behat_config = None
  tests_failed = False
  composer_lock = True

  # Set SSH key if needed
  ssh_key = None
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

  # Define primary host
  common.Utils.define_host(config, buildtype, repo)

  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster)

  # Check where we're deploying to - abort if nothing set in config.ini
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Make sure /var/www/config exists
  execute(Multisite.create_config_dir)

  # Compile variables for feature branch builds (if applicable)
  FeatureBranches.configure_feature_branch(buildtype, config, branch)
  print "Feature branch debug information below:"
  print "httpauth_pass: %s" % FeatureBranches.httpauth_pass
  print "ssl_enabled: %s" % FeatureBranches.ssl_enabled
  print "ssl_cert: %s" % FeatureBranches.ssl_cert
  print "ssl_ip: %s" % FeatureBranches.ssl_ip
  print "drupal_common_config: %s" % FeatureBranches.drupal_common_config

  # Prepare variables for various Drupal tasks
  if config.has_section("Features"):
    fra = config.getboolean("Features", "fra")
    if fra:
      branches = Drupal.drush_fra_branches(config)

  readonlymode = Drupal.configure_readonlymode(config)

  # Compile a site mapping, which is needed if this is a multisite build
  mapping = Multisite.configure_site_mapping(repo, mapping, config)

  # These are our standard deployment hooks, such as config_export
  # All of the standard hooks are in hooks/StandardHooks.py
  # First, declare the variables that relate to our hooks
  # An example would be:
  # [Hooks]
  # config_export: True
  #
  config_export = Drupal.configure_config_export(config)

  # Prepare Behat variables
  if config.has_section("Behat"):
    behat_config = DrupalTests.prepare_behat_tests(config, buildtype)

  # Set a URL if one wasn't already provided and clean it up if it was
  url = common.Utils.generate_url(url, repo, branch)

  # Pause StatusCake monitoring
  statuscake_paused = common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid, "pause")

  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  if dontbuild:
    print "===> Not actually doing a proper build. This is a debugging build."
  else:
    execute(common.Utils.clone_repo, repo, repourl, branch, build, None, ssh_key)

    # Gitflow workflow means '/' in branch names, need to clean up.
    branch = common.Utils.generate_branch_name(branch)
    print "===> Branch is %s" % branch

    # Let's allow developers to perform some early actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

    # Because execute() returns an array of values returned keyed by hostname
    drupal_version = DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config)
    print "===> Set drupal_version variable to %s" % drupal_version

    if drupal_version != '8':
      importconfig = "no"

    if drupal_version == '8' and composer is True:
      execute(Drupal.run_composer_install, repo, branch, build, composer_lock, no_dev)

    new_sites = Multisite.check_for_new_installs(repo, branch, build, mapping)
    if new_sites is not None:
      execute(Multisite.new_site_live_symlink, repo, branch, build, mapping, new_sites)
      execute(Multisite.new_site_files, repo, branch, build, mapping, new_sites)
      execute(Multisite.new_site_create_database, repo, branch, build, buildtype, profile, mapping, new_sites, drupal_version, cluster, rds, config)
      execute(Multisite.new_site_copy_settings, repo, branch, build, mapping, new_sites)
      execute(Multisite.new_site_force_dbupdate, repo, branch, build, mapping, new_sites)
      execute(Multisite.new_site_build_vhost, repo, branch, mapping, new_sites, webserverport)
      execute(Multisite.generate_drush_alias, repo, branch, mapping, new_sites)
      execute(Multisite.generate_drush_cron, repo, branch, mapping, new_sites)
      execute(Multisite.new_site_fix_perms, repo, branch, mapping, new_sites, drupal_version)

    execute(Multisite.backup_db, repo, branch, build, mapping, new_sites)
    execute(Multisite.adjust_files_symlink, repo, branch, build, mapping, new_sites)
    execute(Multisite.adjust_settings_php, repo, branch, build, buildtype, mapping, new_sites)

    # Let's allow developers to perform some actions right after Drupal is built
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', hosts=env.roledefs['app_all'])

    #environment_indicator(repo, branch, build, buildtype)
    execute(Multisite.drush_status, repo, branch, build, buildtype, mapping, new_sites, revert_settings=True)
    if doupdates == 'yes':
      execute(Multisite.drush_updatedb, repo, branch, build, buildtype, mapping, new_sites, drupal_version)
    if fra:
      if branch in branches:
        execute(Multisite.drush_fra, repo, branch, build, buildtype, mapping, new_sites, drupal_version)
    #drush_status(repo, branch, build, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)
    execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
    execute(Multisite.secure_admin_password, repo, branch, build, mapping, drupal_version)
    execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
    for alias,buildsite in mapping.iteritems():
      execute(Multisite.drush_cache_clear, repo, branch, build, buildsite, drupal_version, hosts=env.roledefs['app_primary'])

    # Let's allow developers to perform some post-build actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

    # Resume StatusCake monitoring
    if statuscake_paused:
      common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid)

    execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])
