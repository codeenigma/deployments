from fabric.api import *
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
import common.MySQL
import Magento
import InitialBuild

# Override the shell env variable in Fabric, so that we don't see 
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'


# Main build script
@task
def main(repo, repourl, branch, build, buildtype, url=None, magento_email=None, db_name=None, db_username=None, db_password=None, dump_file=None, magento_marketplace_username=None, magento_marketplace_password=None, keepbuilds=10, buildtype_override=False, httpauth_pass=None, cluster=False, with_no_dev=True, statuscakeuser=None, statuscakekey=None, statuscakeid=None, webserverport='8080', mysql_version=5.5, rds=False, autoscale=None, mysql_config='/etc/mysql/debian.cnf', config_filename='config.ini', www_root='/var/www', php_ini_file=None):
  
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
  site_root = www_root + '/%s_%s_%s' % (repo, buildtype, build)
  site_link = www_root + '/live.%s.%s' % (repo, buildtype)

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Determine web server
  webserver = "nginx"
  with settings(hide('running', 'warnings', 'stdout', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd']
    for service in services:
      if run('pgrep -lf %s | egrep -v "bash|grep" > /dev/null' % service).return_code == 0:
        webserver = service

  # Can be set in the config.ini [Build] section
  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")
  notifications_email = common.ConfigFile.return_config_item(config, "Build", "notifications_email")
  # Need to keep potentially passed in 'url' value as default
  url = common.ConfigFile.return_config_item(config, "Build", "url", "string", url)
  # This cleans a provided URL and will generate one if none has been provided
  url = common.Utils.generate_url(url, repo, buildtype)
  php_ini_file = common.ConfigFile.return_config_item(config, "Build", "php_ini_file", "string", php_ini_file)

  # Can be set in the config.ini [Magento] section
  magento_password = common.ConfigFile.return_config_item(config, "Magento", "magento_username", "string", common.Utils._gen_passwd(8, True))
  magento_username = common.ConfigFile.return_config_item(config, "Magento", "magento_username", "string", "admin")
  magento_email = common.ConfigFile.return_config_item(config, "Magento", "magento_email", "string", magento_email)
  magento_firstname = common.ConfigFile.return_config_item(config, "Magento", "magento_firstname", "string", "Some")
  magento_lastname = common.ConfigFile.return_config_item(config, "Magento", "magento_lastname", "string", "User")
  magento_admin_path = common.ConfigFile.return_config_item(config, "Magento", "magento_admin_path", "string", "admin")
  magento_mode = common.ConfigFile.return_config_item(config, "Magento", "magento_mode", "string", "production")
  magento_sample_data = common.ConfigFile.return_config_item(config, "Magento", "magento_sample_data", "boolean", False)
  magento_marketplace_username = common.ConfigFile.return_config_item(config, "Magento", "magento_marketplace_username", "string", magento_marketplace_username)
  magento_marketplace_password = common.ConfigFile.return_config_item(config, "Magento", "magento_marketplace_password", "string", magento_marketplace_password)
  # Can be set in the config.ini [Database] section
  db_name = common.ConfigFile.return_config_item(config, "Database", "db_name")
  db_username = common.ConfigFile.return_config_item(config, "Database", "db_username")
  db_password = common.ConfigFile.return_config_item(config, "Database", "db_password")
  # Need to keep potentially passed in MySQL version and config path as defaults
  mysql_config = common.ConfigFile.return_config_item(config, "Database", "mysql_config", "string", mysql_config)
  mysql_version = common.ConfigFile.return_config_item(config, "Database", "mysql_version", "string", mysql_version)
  dump_file = common.ConfigFile.return_config_item(config, "Database", "dump_file")

  # Can be set in the config.ini [Composer] section
  composer = common.ConfigFile.return_config_item(config, "Composer", "composer", "boolean", True)
  composer_lock = common.ConfigFile.return_config_item(config, "Composer", "composer_lock", "boolean", True)
  no_dev = common.ConfigFile.return_config_item(config, "Composer", "no_dev", "boolean", True)

  # Can be set in the config.ini [Testing] section
  # PHPUnit is in common/Tests because it can be used for any PHP application
  phpunit_run = common.ConfigFile.return_config_item(config, "Testing", "phpunit_run", "boolean", False)
  phpunit_fail_build = common.ConfigFile.return_config_item(config, "Testing", "phpunit_fail_build", "boolean", False)
  phpunit_group = common.ConfigFile.return_config_item(config, "Testing", "phpunit_group", "string", "unit")
  phpunit_test_directory = common.ConfigFile.return_config_item(config, "Testing", "phpunit_test_directory")
  phpunit_path = common.ConfigFile.return_config_item(config, "Testing", "phpunit_path", "string", "vendor/phpunit/phpunit/phpunit")

  # Run the tasks.
  execute(common.Utils.clone_repo, repo, repourl, branch, build, buildtype, ssh_key, hosts=env.roledefs['app_all'])

  # Pause StatusCake monitoring
  statuscake_paused = common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid, "pause")

  # Check the php_ini_file string isn't doing anything naughty
  malicious_code = False
  malicious_code = common.Utils.detect_malicious_strings([';', '&&'], php_ini_file)
  # Set CLI PHP version, if we need to
  if php_ini_file and not malicious_code:
    run("export PHPRC='%s'" % php_ini_file)

  # Let's allow developers to perform some early actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

  # If this is the first build, attempt to install the site for the first time.
  with settings(hide('warnings', 'stderr'), warn_only=True):
    if run("find %s -type f -name mage" % (site_link)).failed:
      fresh_install = True
    else:
      fresh_install = False

  if fresh_install is True:
    print "===> Looks like the site %s doesn't exist. We'll try and install it..." % url

    # Check for expected shared directories
    execute(common.Utils.create_shared_directory, hosts=env.roledefs['app_all'])
    execute(common.Utils.initial_build_create_live_symlink, repo, buildtype, build, hosts=env.roledefs['app_all'])

    try:
      execute(InitialBuild.initial_magento_folders, repo, buildtype, www_root, site_root, user)
      execute(InitialBuild.initial_magento_build, repo, repourl, branch, user, url, www_root, site_root, buildtype, build, config, composer, composer_lock, no_dev, rds, db_name, db_username, mysql_version, db_password, mysql_config, dump_file, magento_password, magento_username, magento_email, magento_firstname, magento_lastname, magento_admin_path, magento_mode, magento_marketplace_username, magento_marketplace_password, cluster)
      execute(Magento.adjust_files_symlink, repo, buildtype, www_root, site_root, user)
      if magento_sample_data:
        execute(InitialBuild.initial_build_sample_data, site_root, user, magento_marketplace_username, magento_marketplace_password)
        execute(Magento.magento_compilation_steps, site_root, user)
      execute(InitialBuild.initial_build_vhost, webserver, repo, buildtype, url, webserverport)
      if httpauth_pass:
        common.Utils.create_httpauth(webserver, repo, buildtype, url, httpauth_pass)
      # Restart services
      execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
      execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
      execute(common.Services.reload_webserver, hosts=env.roledefs['app_all'])

      execute(Magento.generate_magento_cron, repo, buildtype, site_link, autoscale)

      # Let's allow developers to perform some post-build actions if they need to
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-initial', hosts=env.roledefs['app_all'])
    except:
      e = sys.exc_info()[1]
      raise SystemError(e)


  # Not an initial build, let's rebuild the site
  else:
    print "===> Looks like the site %s exists already. We'll try and launch a new build..." % url
    try:
      print "===> Taking a database backup of the Magento database..."
      # Get the credentials for Magento in order to be able to dump the database
      with settings(hide('stdout', 'running')):
        db_name = run("grep dbname %s/www/app/etc/env.php | awk {'print $3'} | head -1 | cut -d\\' -f2" % site_link)
      execute(common.MySQL.mysql_backup_db, db_name, build, True)

      # Start Magento tasks
      execute(Magento.adjust_files_symlink, repo, buildtype, www_root, site_root, user)
      execute(Magento.magento_compilation_steps, site_root, user)
      execute(Magento.magento_maintenance_mode, site_root, 'enable')
      execute(common.Utils.adjust_live_symlink, repo, branch, build, buildtype)

      # Let's allow developers to perform some actions right after Magento is built
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', hosts=env.roledefs['app_all'])

      # Then carry on with db updates
      execute(Magento.magento_database_updates, site_root)
      execute(Magento.magento_maintenance_mode, site_root, 'disable')

      # Restart services
      execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
      execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
      execute(common.Services.reload_webserver, hosts=env.roledefs['app_all'])

      execute(Magento.generate_magento_cron, repo, buildtype, site_link, autoscale)

      # Let's allow developers to perform some post-build actions if they need to
      execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

      execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, buildtype, hosts=env.roledefs['app_all'])
    except:
      e = sys.exc_info()[1]
      raise SystemError(e)

  # Now let's do some post-build stuff

  # Run phpunit tests
  if phpunit_run:
    phpunit_tests_failed = common.Tests.run_phpunit_tests(site_root + '/www', phpunit_group, phpunit_test_directory, phpunit_path)
    if phpunit_tests_failed:
      print "####### phpunit tests failed but the build is set to disregard... continuing, but you should review your test output"
    else:
      print "===> phpunit tests ran successfully."
  else:
    print "===> No phpunit tests."

  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-tests', hosts=env.roledefs['app_all'])

  # Unset CLI PHP version if we need to
  if php_ini_file:
    run("export PHPRC=''")

  # Resume StatusCake monitoring
  if statuscake_paused:
    common.Utils.statuscake_state(statuscakeuser, statuscakekey, statuscakeid)

  # If this is autoscale at AWS, let's update the tarball in S3
  if autoscale:
    execute(common.Utils.tarball_up_to_s3, www_root, repo, buildtype, build, autoscale)

  print "####### BUILD COMPLETE."
  # @TODO: No revert behaviour as yet
