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
import common.Tests
import AdjustConfiguration
import Drupal
import DrupalTests
import DrupalUtils
import FeatureBranches
import InitialBuild
import Revert
import StandardHooks
import Autoscale
# Needed to get variables set in modules back into the main script
from DrupalTests import *
from FeatureBranches import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

global config


# Main build script
@task
def main(repo, repourl, build, branch, buildtype, keepbuilds=10, url=None, freshdatabase="Yes", syncbranch=None, sanitise="no", import_config=False, statuscakeuser=None, statuscakekey=None, statuscakeid=None, restartvarnish="yes", cluster=False, sanitised_email=None, sanitised_password=None, webserverport='8080', mysql_version=5.5, rds=False, autoscale=None, mysql_config='/etc/mysql/debian.cnf', config_filename='config.ini'):

  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.buildtype_config_file(buildtype, config_filename)

  # Now we need to figure out what server(s) we're working with
  # Define primary host
  common.Utils.define_host(config, buildtype, repo)
  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster, autoscale)
  # Check where we're deploying to - abort if nothing set in config.ini
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set some default config options and variables
  user = "jenkins"
  previous_build = ""
  previous_db = ""
  statuscake_paused = False

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Can be set in the config.ini [Build] section
  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")
  notifications_email = common.ConfigFile.return_config_item(config, "Build", "notifications_email")
  # Need to keep potentially passed in 'url' value as default
  url = common.ConfigFile.return_config_item(config, "Build", "url", "string", url)

  # Can be set in the config.ini [Database] section
  db_name = common.ConfigFile.return_config_item(config, "Database", "db_name")
  db_username = common.ConfigFile.return_config_item(config, "Database", "db_username")
  db_password = common.ConfigFile.return_config_item(config, "Database", "db_password")
  # Need to keep potentially passed in MySQL version and config path as defaults
  mysql_config = common.ConfigFile.return_config_item(config, "Database", "mysql_config", "string", mysql_config)
  mysql_version = common.ConfigFile.return_config_item(config, "Database", "mysql_version", "string", mysql_version)
  dump_file = common.ConfigFile.return_config_item(config, "Database", "dump_file")

  # Can be set in the config.ini [Drupal] section
  drupal_version = common.ConfigFile.return_config_item(config, "Drupal", "drupal_version")
  profile = common.ConfigFile.return_config_item(config, "Drupal", "profile", "string", "minimal")
  do_updates = common.ConfigFile.return_config_item(config, "Drupal", "do_updates", "boolean", True)
  run_cron = common.ConfigFile.return_config_item(config, "Drupal", "run_cron", "boolean", False)
  import_config = common.ConfigFile.return_config_item(config, "Drupal", "import_config", "boolean", import_config)
  ### @TODO: deprecated, can be removed later
  fra = common.ConfigFile.return_config_item(config, "Features", "fra", "boolean", False, True, True, replacement_section="Drupal")
  # This is the correct location for 'fra' - note, respect the deprecated value as default
  fra = common.ConfigFile.return_config_item(config, "Drupal", "fra", "boolean", fra)
  ### @TODO: deprecated, can be removed later
  readonlymode = common.ConfigFile.return_config_item(config, "Readonly", "readonly", "string", "maintenance", True, True, replacement_section="Drupal")
  # This is the correct location for 'readonly' - note, respect the deprecated value as default
  readonlymode = common.ConfigFile.return_config_item(config, "Drupal", "readonly", "string", readonlymode)
  ### @TODO: deprecated, can be removed later
  config_export = common.ConfigFile.return_config_item(config, "Hooks", "config_export", "boolean", False, True, True, replacement_section="Drupal")
  # This is the correct location for 'config_export' - note, respect the deprecated value as default
  config_export = common.ConfigFile.return_config_item(config, "Drupal", "config_export", "boolean", config_export)

  # Can be set in the config.ini [Composer] section
  composer = common.ConfigFile.return_config_item(config, "Composer", "composer", "boolean", True)
  composer_lock = common.ConfigFile.return_config_item(config, "Composer", "composer_lock", "boolean", True)
  no_dev = common.ConfigFile.return_config_item(config, "Composer", "no_dev", "boolean", True)

  # Can be set in the config.ini [Testing] section
  phpunit_run = common.ConfigFile.return_config_item(config, "Testing", "phpunit_run", "boolean", False)
  phpunit_fail_build = common.ConfigFile.return_config_item(config, "Testing", "phpunit_fail_build", "boolean", False)
  phpunit_group = common.ConfigFile.return_config_item(config, "Testing", "phpunit_group", "string", "unit")
  phpunit_test_directory = common.ConfigFile.return_config_item(config, "Testing", "phpunit_test_directory", "string", "www/modules/custom")
  phpunit_path = common.ConfigFile.return_config_item(config, "Testing", "phpunit_path", "string", "vendor/phpunit/phpunit/phpunit")

  # Set SSH key if needed
  # @TODO: this needs to be moved to config.ini for Code Enigma GitHub projects
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

  # Prepare Behat variables
  behat_config = None
  behat_tests_failed = False
  if config.has_section("Behat"):
    behat_config = DrupalTests.prepare_behat_tests(config, buildtype)

  # Pause StatusCake monitoring
  statuscake_paused = common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid, "pause")

  # Run the tasks.
  # --------------
  execute(common.Utils.clone_repo, repo, repourl, branch, build, None, ssh_key, hosts=env.roledefs['app_all'])

  # Gitflow workflow means '/' in branch names, need to clean up.
  branch = common.Utils.generate_branch_name(branch)
  print "===> Branch is %s" % branch

  # Set branches to be treated as feature branches
  # Regardless of whether or not 'fra' is set, we need to set 'branches'
  # our our existing_build_wrapper() function gets upset later.
  feature_branches = Drupal.drush_fra_branches(config, branch)

  # Now we have the codebase and a clean branch name we can figure out the Drupal version
  # Don't use execute() because it returns an array of values returned keyed by hostname
  drupal_version = DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config)
  print "===> the drupal_version variable is set to %s" % drupal_version

  # Let's allow developers to perform some early actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

  # @TODO: This will be a bug when Drupal 9 comes out!
  # We need to cast version as an integer and use < 8
  if drupal_version != '8':
    import_config = False
  if drupal_version == '8' and composer is True:
    execute(Drupal.run_composer_install, repo, branch, build, composer_lock, no_dev)

  # Compile a site mapping, which is needed if this is a multisite build
  # Just sets to 'default' if it is not
  mapping = {}
  mapping = Drupal.configure_site_mapping(repo, mapping, config)
  # Run new installs
  for alias,site in mapping.iteritems():
    # Compile variables for feature branch builds (if applicable)
    FeatureBranches.configure_feature_branch(buildtype, config, branch, alias)
    print "Feature branch debug information below:"
    print "httpauth_pass: %s" % FeatureBranches.httpauth_pass
    print "ssl_enabled: %s" % FeatureBranches.ssl_enabled
    print "ssl_cert: %s" % FeatureBranches.ssl_cert
    print "ssl_ip: %s" % FeatureBranches.ssl_ip
    print "drupal_common_config: %s" % FeatureBranches.drupal_common_config
    print "featurebranch_url: %s" % FeatureBranches.featurebranch_url

    if freshdatabase == "Yes" and buildtype == "custombranch":
      # For now custombranch builds to clusters cannot work
      dump_file = Drupal.prepare_database(repo, branch, build, alias, syncbranch, env.host_string, sanitise, drupal_version, sanitised_password, sanitised_email)

    if FeatureBranches.featurebranch_url is not None:
      url = FeatureBranches.featurebranch_url

    url = common.Utils.generate_url(url, alias, branch)
    # Now check if we have a Drush alias with that name. If not, run an install
    with settings(hide('warnings', 'stderr'), warn_only=True):
      if run("drush sa | grep ^@%s_%s$ > /dev/null" % (alias, branch)).failed:
        print "Didn't find a Drush alias %s_%s so we'll install this new site %s" % (alias, branch, url)
        initial_build_wrapper(url, repo, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, rds, drupal_version, import_config, webserverport, behat_config, autoscale)
      else:
        # Otherwise it's an existing build
        existing_build_wrapper(url, repo, branch, build, buildtype, alias, site, no_dev, config, config_export, drupal_version, readonlymode, notifications_email, autoscale, do_updates, import_config, fra, run_cron, feature_branches)

    # After any build we want to run all the available automated tests
    test_runner(repo, branch, build, alias, buildtype, url, ssl_enabled, config, behat_config, drupal_version, phpunit_run, phpunit_group, phpunit_test_directory, phpunit_path, phpunit_fail_build, site)

    # Now everything should be in a good state, let's enable environment indicator for this site, if present
    execute(Drupal.environment_indicator, repo, branch, build, buildtype, alias, site, drupal_version)

    # If this is a single site, we're done with the 'url' variable anyway
    # If this is a multisite, we have to set it to None so a new 'url' gets generated on the next pass
    url = None

  # Resume StatusCake monitoring
  if statuscake_paused:
    common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid)

  # If this is autoscale at AWS, let's update the tarball in S3
  if autoscale:
    execute(common.Utils.tarball_up_to_s3, repo, buildtype, build, autoscale)

  #commit_new_db(repo, repourl, url, build, branch)
  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])

  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/revert', '/home/jenkins', mode=0755).failed:
    print "####### BUILD COMPLETE. Could not copy the revert script to the application server, revert will need to be handled manually"
  else:
    print "####### BUILD COMPLETE. If you need to revert this build, run the following command: sudo /home/jenkins/revert -b %s -d %s -s /var/www/live.%s.%s -a %s_%s" % (previous_build, previous_db, repo, branch, repo, branch)
  # If any of our tests failed, abort the job
  # r23697
  if behat_tests_failed:
    print "Some tests failed. Aborting the job."
    sys.exit(3)


##########################################################
### Wrapper functions after this line.
##########################################################


# Wrapper function for carrying out a first build of a site
@task
def initial_build_wrapper(url, repo, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, rds, drupal_version, import_config, webserverport, behat_config, autoscale):
  print "===> URL is http://%s" % url

  print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url

  # Check for expected shared directories
  execute(common.Utils.create_config_directory, hosts=env.roledefs['app_all'])
  execute(common.Utils.create_shared_directory, hosts=env.roledefs['app_all'])
  # Build out Drupal
  execute(InitialBuild.initial_build_create_live_symlink, repo, branch, build)
  execute(InitialBuild.initial_build, repo, url, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, rds)
  execute(InitialBuild.initial_build_create_files_symlink, repo, branch, build, site, alias)
  execute(InitialBuild.initial_build_move_settings, alias, branch)
  # Configure the server
  execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype, alias, site)
  execute(InitialBuild.initial_build_vhost, repo, url, branch, build, alias, buildtype, FeatureBranches.ssl_enabled, FeatureBranches.ssl_cert, FeatureBranches.ssl_ip, FeatureBranches.httpauth_pass, FeatureBranches.drupal_common_config, webserverport)
  execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build, site)
  # Restart services
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.reload_webserver, hosts=env.roledefs['app_all'])
  # Do some final Drupal config tweaking
  execute(InitialBuild.generate_drush_alias, repo, url, branch, alias)
  execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)
  execute(Drupal.generate_drush_cron, repo, branch)

  # If this is autoscale at AWS, we need to remove *.settings.php from autoscale initial build folders
  if autoscale:
    execute(Autoscale.remove_original_settings_files, repo, site)

  # If this is a custom/feature branch deployment, we want to run drush updb. If it fails,
  # the build will fail, but because this is being run at the end, there shouldn't need to be
  # any manual clean-up first. Everything else will have run, such as generate drush alias and
  # webserver vhost, so the issue can be fixed and the job re-run.
  if buildtype == "custombranch":
    FeatureBranches.initial_db_and_config(repo, branch, build, import_config, drupal_version)
  else:
    execute(InitialBuild.initial_build_updatedb, repo, branch, build, site, drupal_version)
    execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)
    if import_config:
      execute(InitialBuild.initial_build_config_import, repo, branch, build, site, drupal_version)
      execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-initial', hosts=env.roledefs['app_all'])


# Wrapper function for building an existing site
@task
def existing_build_wrapper(url, repo, branch, build, buildtype, alias, site, no_dev, config, config_export, drupal_version, readonlymode, notifications_email, autoscale, do_updates, import_config, fra, run_cron, feature_branches):
  print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
  # Grab some information about the current build
  previous_build = common.Utils.get_previous_build(repo, branch, build)
  previous_db = common.Utils.get_previous_db(repo, branch, build)
  execute(Drupal.backup_db, alias, branch, build)

  execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype, alias, site)
  execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build, site)
  execute(AdjustConfiguration.adjust_files_symlink, repo, branch, build, alias, site)

  # Let's allow developers to perform some actions right after Drupal is built
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', hosts=env.roledefs['app_all'])

  # If this is autoscale at AWS, we need to remove *.settings.php from autoscale initial build folders
  if autoscale:
    execute(Autoscale.remove_original_settings_files, repo, site)

  # Export the config if we need to (Drupal 8+)
  if config_export:
    execute(StandardHooks.config_export, repo, branch, build, drupal_version)
  execute(Drupal.drush_status, repo, branch, build, site, alias, revert_settings=True)

  # Time to update the database!
  if do_updates == True:
    execute(Drupal.go_offline, repo, branch, build, alias, readonlymode, drupal_version)
    execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)
    execute(Drupal.drush_updatedb, repo, branch, build, site, alias, drupal_version)            # This will revert the database if it fails
    if fra == True:
      if branch in feature_branches:
        execute(Drupal.drush_fra, repo, branch, build, site, alias, drupal_version)
    if run_cron == True:
      execute(Drupal.drush_cron, repo, branch, build, site, drupal_version)
    execute(Drupal.drush_status, repo, branch, build, site, alias, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

    # Cannot use try: because execute() return not compatible.
    execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
    # This will revert the database if fails
    live_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    this_build = "/var/www/%s_%s_%s" % (repo, branch, build)
    # The above paths should match - something is wrong if they don't!
    if not this_build == live_build:
      Revert._revert_db(alias, branch, build)
      Revert._revert_settings(repo, branch, build, site, alias)
      raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

    if import_config:
      execute(Drupal.config_import, repo, branch, build, site, alias, drupal_version, previous_build) # This will revert database, settings and live symlink if it fails.

    # Let's allow developers to use other config management for imports, such as CMI
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='config', hosts=env.roledefs['app_primary'])

    execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)
    execute(Drupal.go_online, repo, branch, build, alias, previous_build, readonlymode, drupal_version) # This will revert the database and switch the symlink back if it fails
    execute(Drupal.check_node_access, alias, branch, notifications_email)

  else:
    print "####### WARNING: by skipping database updates we cannot check if the node access table will be rebuilt. If it will this is an intrusive action that may result in an extended outage."
    execute(Drupal.drush_status, repo, branch, build, site, alias, revert=True) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

    # Cannot use try: because execute() return not compatible.
    execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
    # This will revert the database if fails
    live_build = run("readlink /var/www/live.%s.%s" % (repo, branch))
    this_build = "/var/www/%s_%s_%s" % (repo, branch, build)
    # The above paths should match - something is wrong if they don't!
    if not this_build == live_build:
      Revert._revert_db(alias, branch, build)
      Revert._revert_settings(repo, branch, build, site, alias)
      raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

    if import_config:
      execute(Drupal.config_import, repo, branch, build, site, alias, drupal_version, previous_build) # This will revert database, settings and live symlink if it fails.

    # Let's allow developers to use other config management for imports, such as CMI
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='config', hosts=env.roledefs['app_primary'])

    execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)

  # Final clean up and run tests, if applicable
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
  execute(Drupal.generate_drush_cron, repo, branch)

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])


# Wrapper function for runnning automated tests on a site
@task
def test_runner(repo, branch, build, alias, buildtype, url, ssl_enabled, config, behat_config, drupal_version, phpunit_run, phpunit_group, phpunit_test_directory, phpunit_path, phpunit_fail_build, site):
  # Run simpletest tests
  execute(DrupalTests.run_tests, repo, branch, build, config)

  # Run behat tests
  if behat_config:
    if buildtype in behat_config['behat_buildtypes']:
      behat_tests_failed = DrupalTests.run_behat_tests(repo, branch, build, alias, buildtype, url, ssl_enabled, behat_config['behat_junit'], drupal_version, behat_config['behat_tags'], behat_config['behat_modules'])
  else:
    print "===> No behat tests."

  # Run phpunit tests
  if phpunit_run:
    # @TODO: We really need to figure out how to use execute() and fish returned variables from the response
    phpunit_tests_failed = common.Tests.run_phpunit_tests(repo, branch, build, phpunit_group, phpunit_test_directory, phpunit_path)
    if phpunit_fail_build and phpunit_tests_failed:
      Revert._revert_db(alias, branch, build)
      Revert._revert_settings(repo, branch, build, site, alias)
      raise SystemExit("####### phpunit tests failed and you have specified you want to fail and roll back when this happens. Reverting database")
    elif phpunit_tests_failed:
      print "####### phpunit tests failed but the build is set to disregard... continuing, but you should review your test output"
    else:
      print "===> phpunit tests ran successfully."
  else:
    print "===> No phpunit tests."

  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-tests', hosts=env.roledefs['app_all'])
