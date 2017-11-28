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
import AdjustConfiguration
import Drupal
import DrupalTests
import DrupalUtils
import FeatureBranches
import InitialBuild
import Revert
import StandardHooks
# Needed to get variables set in modules back into the main script
from DrupalTests import *
from FeatureBranches import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

global config


@task
def main(repo, repourl, build, branch, buildtype, url=None, profile="minimal", keepbuilds=10, runcron="False", doupdates="Yes", freshdatabase="Yes", syncbranch=None, sanitise="no", statuscakeuser=None, statuscakekey=None, statuscakeid=None, importconfig="yes", restartvarnish="yes", cluster=False, sanitised_email=None, sanitised_password=None, webserverport='8080', rds=False, config_filename='config.ini'):

  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.buildtype_config_file(buildtype, config_filename)

  # Define variables
  drupal_version = None
  user = "jenkins"

  # Set SSH key if needed
  ssh_key = None
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

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

  #httpauth_pass = None
  #ssl_enabled = False
  #ssl_cert = None
  #ssl_ip = None
  #drupal_common_config = None

  # Define primary host
  common.Utils.define_host(config, buildtype, repo)

  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster)

  # Check where we're deploying to - abort if nothing set in config.ini
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

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
    if fra == True:
      branches = Drupal.drush_fra_branches(config)
  readonlymode = Drupal.configure_readonlymode(config)

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
  with settings(warn_only=True):
    cleanbranch = branch.replace('/', '-')
    if run('drush sa | grep \'^@\?%s_%s$\' > /dev/null' % (repo, cleanbranch)).failed:
      fresh_install = True
    else:
      fresh_install = False

  if fresh_install == True:
    print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url
    execute(common.Utils.clone_repo, repo, repourl, branch, build, ssh_key, hosts=env.roledefs['app_all'])

    # Gitflow workflow means '/' in branch names, need to clean up.
    branch = common.Utils.generate_branch_name(branch)
    print "===> Branch is %s" % branch

    print "===> URL is http://%s" % url

    # Let's allow developers to perform some early actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

    # Because execute() returns an array of values returned keyed by hostname
    drupal_version = DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config)
    print "===> Set drupal_version variable to %s" % drupal_version

    if drupal_version != '8':
      importconfig = "no"
    if drupal_version == '8':
      execute(Drupal.run_composer_install, repo, branch, build)
    if freshdatabase == "Yes" and buildtype == "custombranch":
      # For now custombranch builds to clusters cannot work
      Drupal.prepare_database(repo, branch, build, syncbranch, env.host_string, sanitise, drupal_version, sanitised_password, sanitised_email)

    execute(common.Utils.create_config_directory, hosts=env.roledefs['app_all'])
    execute(common.Utils.create_shared_directory, hosts=env.roledefs['app_all'])
    execute(InitialBuild.initial_build_create_live_symlink, repo, branch, build)
    execute(InitialBuild.initial_build, repo, url, branch, build, profile, buildtype, sanitise, config, drupal_version, sanitised_password, sanitised_email, cluster, rds)
    execute(InitialBuild.initial_build_create_files_symlink, repo, branch, build)
    execute(InitialBuild.initial_build_move_settings, repo, branch)
    execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype)
    execute(InitialBuild.initial_build_vhost, repo, url, branch, build, buildtype, FeatureBranches.ssl_enabled, FeatureBranches.ssl_cert, FeatureBranches.ssl_ip, FeatureBranches.httpauth_pass, FeatureBranches.drupal_common_config, webserverport)
    execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build)
    execute(Drupal.environment_indicator, repo, branch, build, buildtype, drupal_version)
    execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.reload_webserver, hosts=env.roledefs['app_all'])
    execute(InitialBuild.generate_drush_alias, repo, url, branch)
    execute(Drupal.secure_admin_password, repo, branch, build, drupal_version)
    execute(Drupal.generate_drush_cron, repo, branch)

    # If this is a custom/feature branch deployment, we want to run drush updb. If it fails,
    # the build will fail, but because this is being run at the end, there shouldn't need to be
    # any manual clean-up first. Everything else will have run, such as generate drush alias and
    # webserver vhost, so the issue can be fixed and the job re-run.
    if buildtype == "custombranch":
      FeatureBranches.initial_db_and_config(repo, branch, build, importconfig, drupal_version)

    if behat_config:
      if buildtype in behat_config['behat_buildtypes']:
        tests_failed = DrupalTests.run_behat_tests(repo, branch, build, buildtype, url, ssl_enabled, behat_config['behat_junit'], drupal_version, behat_config['behat_tags'], behat_config['behat_modules'])
    else:
      print "===> No behat tests."

    # Let's allow developers to perform some post-build actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-initial', hosts=env.roledefs['app_all'])

    # If any of our tests failed, abort the job
    # r23697
    if tests_failed:
      print  "Some tests failed. Aborting the job."
      sys.exit(3)
  else:
    print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
    # Grab some information about the current build
    previous_build = common.Utils.get_previous_build(repo, cleanbranch, build)
    previous_db = common.Utils.get_previous_db(repo, cleanbranch, build)
    execute(Drupal.backup_db, repo, cleanbranch, build)

    execute(common.Utils.clone_repo, repo, repourl, branch, build, ssh_key, hosts=env.roledefs['app_all'])

    # Gitflow workflow means '/' in branch names, need to clean up.
    branch = common.Utils.generate_branch_name(branch)
    print "===> Branch is %s" % branch

    print "===> URL is http://%s" % url

    # Let's allow developers to perform some early actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

    # Because execute() returns an array of values returned keyed by hostname
    drupal_version = DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config)
    print "===> Set drupal_version variable to %s" % drupal_version

    if drupal_version != '8':
      importconfig = "no"
    if freshdatabase == "Yes" and buildtype == "custombranch":
      Drupal.prepare_database(repo, branch, build, syncbranch, env.host_string, sanitise, drupal_version, sanitised_password, sanitised_email, False)
    execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype)
    execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build)
    execute(Drupal.environment_indicator, repo, branch, build, buildtype, drupal_version)
    execute(AdjustConfiguration.adjust_files_symlink, repo, branch, build)
    if drupal_version == '8':
      execute(Drupal.run_composer_install, repo, branch, build)

    # Let's allow developers to perform some actions right after Drupal is built
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', hosts=env.roledefs['app_all'])

    if config_export:
      execute(StandardHooks.config_export, repo, branch, build, drupal_version)
    execute(Drupal.drush_status, repo, branch, build, revert_settings=True)
    if doupdates == "Yes":
      execute(Drupal.go_offline, repo, branch, build, readonlymode, drupal_version)
      execute(Drupal.drush_clear_cache, repo, branch, build, drupal_version)
      execute(Drupal.drush_updatedb, repo, branch, build, drupal_version)            # This will revert the database if it fails
      if fra == True:
        if branch in branches:
          execute(Drupal.drush_fra, repo, branch, build, drupal_version)
      if runcron == "True":
        execute(Drupal.drush_cron, repo, branch, build, drupal_version)
      execute(Drupal.drush_status, repo, branch, build, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

      # Cannot use try: because execute() return not compatible.
      execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
      # This will revert the database if fails
      live_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
      this_build = "/var/www/%s_%s_%s" % (repo, branch, build)
      # The above paths should match - something is wrong if they don't!
      if not this_build == live_build:
        Revert._revert_db(repo, branch, build)
        Revert._revert_settings(repo, branch, build)
        raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

      if importconfig == "yes":
        execute(Drupal.config_import, repo, branch, build, drupal_version, previous_build) # This will revert database, settings and live symlink if it fails.
      execute(Drupal.secure_admin_password, repo, branch, build, drupal_version)
      execute(Drupal.go_online, repo, branch, build, previous_build, readonlymode, drupal_version) # This will revert the database and switch the symlink back if it fails
    else:
      execute(Drupal.drush_status, repo, branch, build, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

      # Cannot use try: because execute() return not compatible.
      execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
      # This will revert the database if fails
      live_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
      this_build = "/var/www/%s_%s_%s" % (repo, branch, build)
      # The above paths should match - something is wrong if they don't!
      if not this_build == live_build:
        Revert._revert_db(repo, branch, build)
        Revert._revert_settings(repo, branch, build)
        raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

      if importconfig == "yes":
        execute(Drupal.config_import, repo, branch, build, drupal_version) # This will revert database, settings and live symlink if it fails.
      execute(Drupal.secure_admin_password, repo, branch, build, drupal_version)
    execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
    execute(Drupal.generate_drush_cron, repo, branch)
    execute(DrupalTests.run_tests, repo, branch, build, config)

    # Let's allow developers to perform some post-build actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

    # Resume StatusCake monitoring
    if statuscake_paused:
      common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid)

    if behat_config:
      if buildtype in behat_config['behat_buildtypes']:
        tests_failed = DrupalTests.run_behat_tests(repo, branch, build, buildtype, url, ssl_enabled, behat_config['behat_junit'], drupal_version, behat_config['behat_tags'], behat_config['behat_modules'])
    else:
        print "===> No behat tests."

    #commit_new_db(repo, repourl, url, build, branch)
    execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])

    script_dir = os.path.dirname(os.path.realpath(__file__))
    if put(script_dir + '/../util/revert', '/home/jenkins', mode=0755).failed:
      print "####### BUILD COMPLETE. Could not copy the revert script to the application server, revert will need to be handled manually"
    else:
      print "####### BUILD COMPLETE. If you need to revert this build, run the following command: sudo /home/jenkins/revert -b %s -d %s -s /var/www/live.%s.%s -a %s_%s" % (previous_build, previous_db, repo, branch, repo, branch)
    # If any of our tests failed, abort the job
    # r23697
    if tests_failed:
      print  "Some tests failed. Aborting the job."
      sys.exit(3)
