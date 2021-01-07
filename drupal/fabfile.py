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
import common.PHP
import AdjustConfiguration
import Drupal
import DrupalTests
import DrupalUtils
import DrupalConfig
import FeatureBranches
import InitialBuild
import Revert
# Needed to get variables set in modules back into the main script
from DrupalTests import *
from FeatureBranches import *
from DrupalConfig import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

global config


# Main build script
@task
def main(repo, repourl, build, branch, buildtype, keepbuilds=10, url=None, freshdatabase="Yes", syncbranch=None, sanitise="no", import_config=False, statuscakeuser=None, statuscakekey=None, statuscakeid=None, restartvarnish="yes", cluster=False, sanitised_email=None, sanitised_password=None, webserverport='8080', mysql_version=5.5, rds=False, autoscale=None, mysql_config='/etc/mysql/debian.cnf', config_filename='config.ini', config_fullpath=False, php_ini_file=None, do_updates=True):

  if config_fullpath == "False":
    config_fullpath = False
  if config_fullpath == "True":
    config_fullpath = True

  if do_updates == "False":
    do_updates = False
  if do_updates == "True":
    do_updates = True

  if import_config == "False":
    import_config = False
  if import_config == "True":
    import_config = True

  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.buildtype_config_file(buildtype, config_filename, fullpath=config_fullpath)

  # Can be set in the config.ini [AWS] section
  aws_credentials = common.ConfigFile.return_config_item(config, "AWS", "aws_credentials", "string", "/home/jenkins/.aws/credentials")
  aws_autoscale_group = common.ConfigFile.return_config_item(config, "AWS", "aws_autoscale_group", "string", "prod-asg-prod")
  aws_package_all_builds = common.ConfigFile.return_config_item(config, "AWS", "aws_package_all_builds", "boolean", False)
  aws_build_tar = common.ConfigFile.return_config_item(config, "AWS", "aws_build_tar", "boolean", True)

  # Now we need to figure out what server(s) we're working with
  # Define primary host
  common.Utils.define_host(config, buildtype, repo)
  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster, autoscale, aws_credentials, aws_autoscale_group)
  # Check where we're deploying to - abort if nothing set in config.ini
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set some default config options and variables
  user = "jenkins"
  previous_build = ""
  previous_db = ""
  statuscake_paused = False
  www_root = "/var/www"
  application_directory = "www"
  site_root = www_root + '/%s_%s_%s' % (repo, branch, build)
  site_link = www_root + '/live.%s.%s' % (repo, branch)
  site_exists = None
  behat_config_file_default = "%s/%s_%s_%s/tests/behat/behat.yml" % (www_root, repo, branch, build)
  composer_lock_outdated = False

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Can be set in the config.ini [Build] section
  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")
  notifications_email = common.ConfigFile.return_config_item(config, "Build", "notifications_email")
  php_ini_file = common.ConfigFile.return_config_item(config, "Build", "php_ini_file", "string", php_ini_file)
  build_hook_version = common.ConfigFile.return_config_item(config, "Build", "build_hook_version", "string", "1")
  # If this is a multisite build, set the url to None so one is generated for every site in the multisite setup. This particular line will ensure the *first* site has its url generated.
  if config.has_section("Sites"):
    print "===> Config file has a [Sites] section, so we'll assume this is a multisite build and set url to None"
    url = None
  # Need to keep potentially passed in 'url' value as default
  else:
    url = common.ConfigFile.return_config_item(config, "Build", "url", "string", url)

  # Can be set in the config.ini [Database] section
  db_name = common.ConfigFile.return_config_item(config, "Database", "db_name")
  db_username = common.ConfigFile.return_config_item(config, "Database", "db_username")
  db_password = common.ConfigFile.return_config_item(config, "Database", "db_password")
  db_backup = common.ConfigFile.return_config_item(config, "Database", "db_backup", "boolean", True)

  # Need to keep potentially passed in MySQL version and config path as defaults
  mysql_config = common.ConfigFile.return_config_item(config, "Database", "mysql_config", "string", mysql_config)
  mysql_version = common.ConfigFile.return_config_item(config, "Database", "mysql_version", "string", mysql_version)
  dump_file = common.ConfigFile.return_config_item(config, "Database", "dump_file")

  # Can be set in the config.ini [Drupal] section
  ### @TODO: deprecated, can be removed later
  drupal_version = common.ConfigFile.return_config_item(config, "Version", "drupal_version", "string", None, True, True, replacement_section="Drupal")
  # This is the correct location for 'drupal_version' - note, respect the deprecated value as default
  drupal_version = common.ConfigFile.return_config_item(config, "Drupal", "drupal_version", "string", drupal_version)
  profile = common.ConfigFile.return_config_item(config, "Drupal", "profile", "string", "minimal")
  run_cron = common.ConfigFile.return_config_item(config, "Drupal", "run_cron", "boolean", False)
  import_config = common.ConfigFile.return_config_item(config, "Drupal", "import_config", "boolean", import_config)
  import_config_method = common.ConfigFile.return_config_item(config, "Drupal", "import_config_method", "string", "cim")
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
  secure_user_one = common.ConfigFile.return_config_item(config, "Drupal", "secure_user_one", "boolean", True)
  do_initial_status_check = common.ConfigFile.return_config_item(config, "Drupal", "do_initial_status_check", "boolean", False)

  # Can be set in the config.ini [Composer] section
  composer = common.ConfigFile.return_config_item(config, "Composer", "composer", "boolean", True)
  composer_lock = common.ConfigFile.return_config_item(config, "Composer", "composer_lock", "boolean", True)
  no_dev = common.ConfigFile.return_config_item(config, "Composer", "no_dev", "boolean", True)
  through_ssh = common.ConfigFile.return_config_item(config, "Composer", "through_ssh", "boolean", False)
  mark_unstable = common.ConfigFile.return_config_item(config, "Composer", "mark_unstable", "boolean", False)

  # Can be set in the config.ini [Testing] section
  # PHPUnit is in common/Tests because it can be used for any PHP application
  phpunit_run = common.ConfigFile.return_config_item(config, "Testing", "phpunit_run", "boolean", False)
  phpunit_fail_build = common.ConfigFile.return_config_item(config, "Testing", "phpunit_fail_build", "boolean", False)
  phpunit_revert_build = common.ConfigFile.return_config_item(config, "Testing", "phpunit_revert_build", "boolean", False)
  phpunit_group = common.ConfigFile.return_config_item(config, "Testing", "phpunit_group", "string", "unit")
  phpunit_test_directory = common.ConfigFile.return_config_item(config, "Testing", "phpunit_test_directory", "string", "%s/modules/custom" % application_directory)
  phpunit_path = common.ConfigFile.return_config_item(config, "Testing", "phpunit_path", "string", "vendor/phpunit/phpunit/phpunit")
  phpunit_install = common.ConfigFile.return_config_item(config, "Testing", "phpunit_install", "boolean", True)
  # CodeSniffer itself is in common/Tests, but standards used here are Drupal specific, see drupal/DrupalTests.py for the wrapper to apply them
  codesniffer = common.ConfigFile.return_config_item(config, "Testing", "codesniffer", "boolean")
  codesniffer_extensions = common.ConfigFile.return_config_item(config, "Testing", "codesniffer_extensions", "string", "php,module,inc,install,test,profile,theme,info,txt,md")
  codesniffer_ignore = common.ConfigFile.return_config_item(config, "Testing", "codesniffer_ignore", "string", "node_modules,bower_components,vendor")
  codesniffer_paths = common.ConfigFile.return_config_item(config, "Testing", "codesniffer_paths", "string", "%s/modules/custom %s/themes/custom" % (application_directory, application_directory))
  # Regex check
  string_to_check = common.ConfigFile.return_config_item(config, "Testing", "string_to_check", "string")
  curl_options = common.ConfigFile.return_config_item(config, "Testing", "curl_options", "string", "sL")
  check_protocol = common.ConfigFile.return_config_item(config, "Testing", "check_protocol", "string", "https")

  # Behat config file location
  behat_config_file = common.ConfigFile.return_config_item(config, "Behat", "behat_config_file", "string", behat_config_file_default)

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

  # Check the php_ini_file string isn't doing anything naughty
  malicious_code = False
  malicious_code = common.Utils.detect_malicious_strings([';', '&&'], php_ini_file)
  # Set CLI PHP version, if we need to
  if php_ini_file and not malicious_code:
    run("export PHPRC='%s'" % php_ini_file)

  # Set branches to be treated as feature branches
  # Regardless of whether or not 'fra' is set, we need to set 'branches'
  # our our existing_build_wrapper() function gets upset later.
  feature_branches = Drupal.drush_fra_branches(config, branch)

  # Now we have the codebase and a clean branch name we can figure out the Drupal version
  # Don't use execute() because it returns an array of values returned keyed by hostname
  drupal_version = int(DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config))
  print "===> the drupal_version variable is set to %s" % drupal_version

  # Let's allow developers to perform some early actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', build_hook_version="1", hosts=env.roledefs['app_all'])
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre-prim', build_hook_version="1", hosts=env.roledefs['app_primary'])

  # @TODO: This will be a bug when Drupal 9 comes out!
  # We need to cast version as an integer and use < 8
  if drupal_version < 8:
    import_config = False
    import_config_method = "cim"
  if drupal_version > 7 and composer is True:
    # Sometimes people use the Drupal Composer project which puts Drupal 8's composer.json file in repo root.
    with shell_env(PHPRC='%s' % php_ini_file):
      with settings(warn_only=True):
        if run("find %s/composer.json" % site_root).return_code == 0:
          path = site_root
        else:
          path = site_root + "/" + application_directory
      if mark_unstable:
        composer_lock_outdated = common.PHP.composer_validate(path)

      execute(common.PHP.composer_command, path, "install", None, no_dev, composer_lock, through_ssh=through_ssh)

  # Compile a site mapping, which is needed if this is a multisite build
  # Just sets to 'default' if it is not
  mapping = {}
  mapping = Drupal.configure_site_mapping(repo, mapping, config)

  # Empty dictionary for sites that have been deployed. A site is added to the
  # dictionary at the *start* of its deployment so it is also reverted if a stage
  # of the deployment fails. Though it is only added if the build is an existing
  # build.
  sites_deployed = {}

  # Empty directory for site URLs that have been deployed. The structure will be
  # alias: url
  site_urls = {}

  # Record the link to the previous build
  previous_build = common.Utils.get_previous_build(repo, branch, build)

  # Take a backup of all sites, then take all sites offline before doing anything else.
  offline_site_exists = None

  for offline_alias,offline_site in mapping.iteritems():
    offline_site_exists = DrupalUtils.check_site_exists(previous_build, offline_site)

    if offline_site_exists:
      drush_runtime_location = "%s/%s/sites/%s" % (previous_build, application_directory, offline_site)
      drush_output = Drupal.drush_status(repo, branch, build, buildtype, offline_site, drush_runtime_location)
      offline_db_name = Drupal.get_db_name(repo, branch, build, buildtype, offline_site, drush_output)

      # If database updates will run, take the site offline
      if do_updates:
        execute(Drupal.go_offline, repo, branch, offline_site, offline_alias, readonlymode, drupal_version)

      # Backup database
      if db_backup:
        previous_db = execute(common.MySQL.mysql_backup_db, offline_db_name, build, True)
        previous_db = previous_db[env.roledefs['app_primary'][0]]

    offline_site_exists = None


  # Run new installs
  for alias,site in mapping.iteritems():
    # Compile variables for feature branch builds (if applicable)
    FeatureBranches.configure_feature_branch(buildtype, config, branch, alias)
    print "===> Feature branch debug information below:"
    print "httpauth_pass: %s" % FeatureBranches.httpauth_pass
    print "ssl_enabled: %s" % FeatureBranches.ssl_enabled
    print "ssl_cert: %s" % FeatureBranches.ssl_cert
    print "ssl_ip: %s" % FeatureBranches.ssl_ip
    print "drupal_common_config: %s" % FeatureBranches.drupal_common_config
    print "featurebranch_url: %s" % FeatureBranches.featurebranch_url
    print "featurebranch_vhost: %s" % FeatureBranches.featurebranch_vhost

    site_exists = DrupalUtils.check_site_exists(previous_build, site)

    cimy_mapping = {}
    if drupal_version > 7 and import_config_method == "cimy":
      cimy_mapping = DrupalConfig.configure_cimy_params(config, site)

    if freshdatabase == "Yes" and buildtype == "custombranch":
      # For now custombranch builds to clusters cannot work
      dump_file = Drupal.prepare_database(repo, branch, build, buildtype, alias, site, syncbranch, env.host_string, sanitise, sanitised_password, sanitised_email)

      # Need to make sure the env.host variable is set correctly, after potentially fetching a database dump from production
      env.host = env.roledefs['app_primary'][0]

    if FeatureBranches.featurebranch_url is not None:
      url = FeatureBranches.featurebranch_url

    url = common.Utils.generate_url(url, alias, branch)
    # Now check if we have a Drush alias with that name. If not, run an install
    with settings(hide('warnings', 'stderr'), warn_only=True):
      # Because this runs in Jenkins home directory, it will use 'system' drush
      if not site_exists:
        print "===> Didn't find a previous build so we'll install this new site %s" % url
        initial_build_wrapper(url, www_root, application_directory, repo, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, rds, drupal_version, import_config, import_config_method, cimy_mapping, webserverport, behat_config, autoscale, php_ini_file, build_hook_version, secure_user_one, previous_build)
      else:
        # Otherwise it's an existing build
        # This does not bring sites online that have been taken offline but not yet deployed
        sites_deployed[alias] = site
        existing_build_wrapper(url, www_root, application_directory, site_root, site_link, repo, branch, build, buildtype, previous_build, db_backup, alias, site, no_dev, config, config_export, drupal_version, do_initial_status_check, readonlymode, notifications_email, autoscale, do_updates, import_config, import_config_method, cimy_mapping, fra, run_cron, feature_branches, php_ini_file, build_hook_version, secure_user_one, sites_deployed)

    # Now everything should be in a good state, let's enable environment indicator for this site, if present
    execute(Drupal.environment_indicator, www_root, repo, branch, build, buildtype, alias, site, drupal_version)

    site_urls[alias] = url

    # If this is a single site, we're done with the 'url' variable anyway
    # If this is a multisite, we have to set it to None so a new 'url' gets generated on the next pass
    url = None

    site_exists = None

  # Adjust the live symlink now that all sites have been deployed. Bring them online after this has happened.
  if previous_build is not None:
    execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])

  # This will revert the database if fails
  live_build = run("readlink %s/live.%s.%s" % (www_root, repo, branch))
  this_build = "%s/%s_%s_%s" % (www_root, repo, branch, build)
  # The above paths should match - something is wrong if they don't!
  if not this_build == live_build:
    # Make sure the live symlink is pointing at the previous working build.
    sudo("ln -nsf %s %s/live.%s.%s" % (www_root, previous_build, repo, branch))
    for revert_alias,revert_site in sites_deployed.iteritems():
      if db_backup:
        common.MySQL.mysql_revert_db(db_name, build)
      else:
        print "####### Due to your config settings no database backup was taken so your database may be broken!"
      execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
      execute(Revert._revert_go_online, repo, branch, build, buildtype, site, drupal_version)
    raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

  if do_updates and previous_build is not None:
    for online_alias,online_site in sites_deployed.iteritems():
      execute(Drupal.go_online, repo, branch, build, buildtype, online_alias, online_site, previous_build, readonlymode, drupal_version, sites_deployed=sites_deployed) # This will revert the database and switch the symlink back if it fails

  # Clear the opcache again after the site has been brought online
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])

  for test_alias,test_site in mapping.iteritems():
    behat_url = site_urls[test_alias]

    # After any build we want to run all the available automated tests
    test_runner(www_root, repo, branch, build, test_alias, buildtype, behat_url, ssl_enabled, db_backup, config, behat_config, behat_config_file, import_config, import_config_method, cimy_mapping, drupal_version, phpunit_run, phpunit_group, phpunit_test_directory, phpunit_path, phpunit_fail_build, phpunit_revert_build, phpunit_install, test_site, codesniffer, codesniffer_extensions, codesniffer_ignore, codesniffer_paths, string_to_check, check_protocol, curl_options, notifications_email, build_hook_version, sites_deployed, previous_build)

    behat_url = None

  # Unset CLI PHP version if we need to
  if php_ini_file:
    run("export PHPRC=''")

  # Resume StatusCake monitoring
  if statuscake_paused:
    common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid)

  # If this is autoscale at AWS, let's update the tarball in S3
  if autoscale:
    # In some cases, you may not want to tarball up the builds.
    # For example, when all builds are tarballed up, you can't
    # reliably have multiple builds running for dev and stage
    # as it will cause an error when the contents of /var/www
    # change.
    if aws_build_tar:
      execute(common.Utils.tarball_up_to_s3, www_root, repo, branch, build, autoscale, aws_package_all_builds)
    else:
      print "Don't create a tarball after this build. Assume the tarballing is happening separately, such as in an overnight job."

  #commit_new_db(repo, repourl, url, build, branch)
  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])

  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/revert', '/home/jenkins', mode=0755).failed:
    print "####### BUILD COMPLETE. Could not copy the revert script to the application server, revert will need to be handled manually"
  else:
    print "####### BUILD COMPLETE. If you need to revert this build, run the following command: sudo /home/jenkins/revert -b %s -d /home/jenkins/dbbackups/%s -s %s/live.%s.%s -a %s_%s" % (previous_build, previous_db, www_root, repo, branch, repo, branch)
  # We have two scenarios where a build might be marked as unstable:
  # 1) If the composer.lock file is outdated (r45198)
  # 2) If any of our tests failed, abort the job (r23697)
  unstable_text = ""
  unstable_build = False

  if behat_tests_failed:
    unstable_text = unstable_text + "####### Some tests failed. Aborting the job.\n"
    unstable_build = True

  if composer_lock_outdated:
    unstable_text = unstable_text + "####### composer.lock is outdated.\n"
    unstable_build = True

  if unstable_build:
    print "%s" % unstable_text
    sys.exit(3)


##########################################################
### Wrapper functions after this line.
##########################################################


# Wrapper function for carrying out a first build of a site
@task
def initial_build_wrapper(url, www_root, application_directory, repo, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, rds, drupal_version, import_config, import_config_method, cimy_mapping, webserverport, behat_config, autoscale, php_ini_file, build_hook_version, secure_user_one, previous_build):
  print "===> URL is http://%s" % url

  print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url

  with shell_env(PHPRC='%s' % php_ini_file):
    # Check for expected shared directories
    execute(common.Utils.create_config_directory, hosts=env.roledefs['app_all'])
    execute(common.Utils.create_shared_directory, hosts=env.roledefs['app_all'])
    if previous_build is None:
      execute(common.Utils.initial_build_create_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
    # Build out Drupal
    execute(InitialBuild.initial_build, repo, url, branch, build, site, alias, profile, buildtype, sanitise, config, db_name, db_username, db_password, mysql_version, mysql_config, dump_file, sanitised_password, sanitised_email, cluster, autoscale, rds)
    execute(InitialBuild.initial_build_create_files_symlink, repo, branch, build, site, alias)
    execute(InitialBuild.initial_build_move_settings, alias, branch)
    # Configure the server
    execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype, alias, site, www_root, application_directory)
    execute(InitialBuild.initial_build_vhost, repo, url, branch, build, alias, buildtype, FeatureBranches.ssl_enabled, FeatureBranches.ssl_cert, FeatureBranches.ssl_ip, FeatureBranches.httpauth_pass, FeatureBranches.drupal_common_config, FeatureBranches.featurebranch_vhost, webserverport)
    execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build, site, www_root, application_directory)

    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])
    # Restart services
    execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.reload_webserver, hosts=env.roledefs['app_all'])
    # Do some final Drupal config tweaking
    execute(InitialBuild.generate_drush_alias, repo, url, branch, alias)
    if secure_user_one:
      execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)
    execute(Drupal.generate_drush_cron, alias, branch, autoscale)

    # If this is a custom/feature branch deployment, we want to run drush updb. If it fails,
    # the build will fail, but because this is being run at the end, there shouldn't need to be
    # any manual clean-up first. Everything else will have run, such as generate drush alias and
    # webserver vhost, so the issue can be fixed and the job re-run.
    if buildtype == "custombranch":
      FeatureBranches.initial_db_and_config(repo, branch, build, site, import_config, import_config_method, cimy_mapping, drupal_version)
    else:
      execute(InitialBuild.initial_build_updatedb, repo, branch, build, site, drupal_version)
      execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)
      if import_config:
        execute(InitialBuild.initial_build_config_import, repo, branch, build, site, drupal_version, import_config_method, cimy_mapping)
        execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)

    # Let's allow developers to perform some post-build actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-prim', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_primary'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-initial', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])


# Wrapper function for building an existing site
@task
def existing_build_wrapper(url, www_root, application_directory, site_root, site_link, repo, branch, build, buildtype, previous_build, db_backup, alias, site, no_dev, config, config_export, drupal_version, do_initial_status_check, readonlymode, notifications_email, autoscale, do_updates, import_config, import_config_method, cimy_mapping, fra, run_cron, feature_branches, php_ini_file, build_hook_version, secure_user_one, sites_deployed):
  print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
  if buildtype == "custombranch":
    print "Site URL is http://%s" % url
  with shell_env(PHPRC='%s' % php_ini_file):
    execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype, alias, site, www_root, application_directory)
    execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build, site, www_root, application_directory)
    execute(AdjustConfiguration.adjust_files_symlink, repo, branch, build, alias, site, www_root, application_directory)

    # Let's allow developers to perform some actions right after Drupal is built
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid-prim', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_primary'])

    # Export the config if we need to (Drupal 8+)
    if config_export:
      execute(Drupal.config_export, repo, branch, build, drupal_version)
    if do_initial_status_check:
      execute(Drupal.drush_status, repo, branch, build, buildtype, site, None, alias, db_backup, revert_settings=True, sites_deployed=sites_deployed)

    # Time to update the database!
    if do_updates == True:
      execute(Drupal.drush_clear_cache, repo, branch, build, site, drupal_version)
      execute(Drupal.drush_updatedb, repo, branch, build, buildtype, site, alias, drupal_version, db_backup, sites_deployed=sites_deployed) # This will revert the database if it fails
      if fra == True:
        if branch in feature_branches:
          execute(Drupal.drush_fra, repo, branch, build, buildtype, site, alias, drupal_version, sites_deployed=sites_deployed)
      if run_cron == True:
        execute(Drupal.drush_cron, repo, branch, build, site, drupal_version)
      execute(Drupal.drush_status, repo, branch, build, buildtype, site, None, alias, db_backup, revert=True, sites_deployed=sites_deployed) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

      if import_config:
        execute(Drupal.config_import, repo, branch, build, buildtype, site, alias, drupal_version, import_config_method, cimy_mapping, previous_build, sites_deployed=sites_deployed) # This will revert database and settings if it fails.

      # Let's allow developers to use other config management for imports, such as CMI
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='config', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_primary'])

      if secure_user_one:
        execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)
      execute(Drupal.check_node_access, repo, alias, branch, build, site, notifications_email)

    else:
      print "####### WARNING: by skipping database updates we cannot check if the node access table will be rebuilt. If it will this is an intrusive action that may result in an extended outage."
      execute(Drupal.drush_status, repo, branch, build, buildtype, site, None, alias, db_backup, revert=True, sites_deployed=sites_deployed) # This will revert the database if it fails (maybe hook_updates broke ability to bootstrap)

      if import_config:
        execute(Drupal.config_import, repo, branch, build, buildtype, site, alias, drupal_version, import_config_method, cimy_mapping, previous_build, sites_deployed=sites_deployed) # This will revert database and settings if it fails.

      # Let's allow developers to use other config management for imports, such as CMI
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='config', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_primary'])

      if secure_user_one:
        execute(Drupal.secure_admin_password, repo, branch, build, site, drupal_version)

    # Final clean up and run tests, if applicable
    execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
    execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
    execute(Drupal.generate_drush_cron, alias, branch, autoscale)

    # Let's allow developers to perform some post-build actions if they need to
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-prim', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_primary'])


# Wrapper function for runnning automated tests on a site
@task
def test_runner(www_root, repo, branch, build, alias, buildtype, url, ssl_enabled, db_backup, config, behat_config, behat_config_file, import_config, import_config_method, cimy_mapping, drupal_version, phpunit_run, phpunit_group, phpunit_test_directory, phpunit_path, phpunit_fail_build, phpunit_revert_build, phpunit_install, site, codesniffer, codesniffer_extensions, codesniffer_ignore, codesniffer_paths, string_to_check, check_protocol, curl_options, notifications_email, build_hook_version, sites_deployed, previous_build):
  # Run simpletest tests
  execute(DrupalTests.run_tests, repo, branch, build, config, drupal_version, codesniffer, codesniffer_extensions, codesniffer_ignore, codesniffer_paths, www_root)

  # Run phpunit tests
  if phpunit_run:
    # @TODO: We really need to figure out how to use execute() and fish returned variables from the response
    path_to_app = "%s/%s_%s_%s" % (www_root, repo, branch, build)
    phpunit_tests_failed = common.Tests.run_phpunit_tests(path_to_app, phpunit_group, phpunit_test_directory, phpunit_path, phpunit_install)
    if phpunit_fail_build and phpunit_tests_failed:
      if phpunit_revert_build:
        if previous_build is not None:
          for revert_alias,revert_site in sites_deployed.iteritems():
            if db_backup:
              execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
            else:
              print "####### Due to your config settings no database backup was taken so your database may be broken!"
            execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          raise SystemExit("####### phpunit tests failed and you have specified you want to fail and roll back when this happens. Reverting database")
        else:
          raise SystemExit("####### phpunit tests failed and you specified you want to fail and roll back when this happens, but this was an initial build so there is nothing to roll back to.")
      else:
        raise SystemExit("####### phpunit tests failed and you have specified you want to fail the build but NOT roll it back.")
    elif phpunit_tests_failed:
      print "####### phpunit tests failed but the build is set to disregard... continuing, but you should review your test output"
    else:
      print "===> phpunit tests ran successfully."
  else:
    print "===> No phpunit tests."

  # Run behat tests
  if behat_config:
    if buildtype in behat_config['behat_buildtypes']:
      behat_tests_failed = DrupalTests.run_behat_tests(repo, branch, build, alias, site, buildtype, url, ssl_enabled, behat_config_file, behat_config['behat_junit'], import_config, import_config_method, cimy_mapping, drupal_version, behat_config['behat_tags'], behat_config['behat_modules'])
  else:
    print "===> No behat tests."

  # Run a regex check
  if url and string_to_check:
    common.Tests.run_regex_check(url, string_to_check, check_protocol, curl_options, notifications_email)

  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-tests', build_hook_version=build_hook_version, alias=alias, site=site, hosts=env.roledefs['app_all'])
