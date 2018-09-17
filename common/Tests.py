from fabric.api import *
from fabric.contrib.files import *
import random
import string
import os
import time
# Custom Code Enigma modules
import common.PHP


# Run phpunit tests
@task
@roles('app_primary')
def run_phpunit_tests(path_to_app, group='unit', path='www', phpunit_path='vendor/phpunit/phpunit/phpunit'):
  phpunit_tests_failed=True
  # We cannot make phpunit work with PHP 5.x, too many problems
  # Detect PHP version
  php_version = run("php -v | head -1 | awk {'print $2'} | cut -d. -f1,2")
  if any(version in php_version for version in [ '5.3', '5.4', '5.5', '5.6' ]):
    # Sorry, PHP too old!
    print "##### Sorry, this version of PHP is too old for current phpunit builds, we cannot run the tests."
    return phpunit_tests_failed
  with cd("%s" % path_to_app):
    # Make sure phpunit is available to use
    # We don't want to fail if it's already there
    with settings(warn_only=True):
      common.PHP.composer_command(path_to_app, "require", "phpunit/phpunit")

    # Now let's look for a phpunit.xml file to use
    phpunit_xml = False
    with settings(warn_only=True):
      # Usual place to expect phpunit.xml
      if run("find %s/phpunit.xml" % path_to_app).return_code == 0:
        phpunit_xml = "phpunit.xml"
      # For Drupal it might be here
      elif run("find %s/www/core/phpunit.xml" % path_to_app).return_code == 0:
        phpunit_xml = "www/core/phpunit.xml"
      # Doesn't look like there is one, let's look for phpunit's default file
      elif run("find %s/phpunit.xml.dist" % path_to_app).return_code == 0:
        phpunit_xml = "phpunit.xml.dist"
      # Nope, last chance, is there a default one in Drupal?
      elif run("find %s/www/core/phpunit.xml.dist" % path_to_app).return_code == 0:
        phpunit_xml = "www/core/phpunit.xml.dist"

    # Not let's run tests
    if phpunit_xml:
      with cd("%s" % path_to_app):
        with settings(warn_only=True):
          if group == '' and path == '':
            if run('%s --configuration=%s' % (phpunit_path, phpunit_xml)).failed:
              print "===> PHPUNIT FAILED!"
            else:
              print "===> Unit tests succeeded"
              phpunit_tests_failed=False
          else:
            if run('%s --configuration=%s --group %s %s' % (phpunit_path, phpunit_xml, group, path)).failed:
              print "===> PHPUNIT FAILED!"
            else:
              print "===> Unit tests succeeded"
              phpunit_tests_failed=False
    else:
      print "===> PHPUNIT FAILED! No phpunit.xml was found so we could not run tests"
      
    return phpunit_tests_failed


# Run CodeSniffer reviews
@task
@roles('app_primary')
def run_codesniffer(path_to_app, extensions="php,inc,txt,md", install=True, standard=None, ignore=None, paths_to_test=None, config_path=None):
  print "===> Running CodeSniffer"
  # Install CodeSniffer for the Jenkins user
  if install:
    common.PHP.composer_command(path_to_app, "require", "squizlabs/php_codesniffer", True, True, True)
  # Load in custom config, if provided
  if config_path:
    run("/home/jenkins/.composer/vendor/bin/phpcs --config-set installed_paths %s" % config_path)
  # Set up string of directories to ignore
  if ignore:
    ignore = " --ignore=%s" % ignore
  else:
    ignore = ""
  # Set up 'standard' to use, if provided
  if standard:
    standard = " --standard=%s" % standard
  else:
    standard = ""
  # Run CodeSniffer itself
  with cd("%s" % path_to_app):
    run("/home/jenkins/.composer/vendor/bin/phpcs %s --extensions=%s %s %s" % (standard, extensions, ignore, paths_to_test))


# Run a regex check of the site we're building
@task
def run_regex_check(url_to_check, string_to_check, check_protocol="https", curl_options="sL", notifications_email=None):
  print "===> Checking the site is up"
  if local("curl -%s %s://%s | grep '%s'" % (curl_options, check_protocol, url_to_check, string_to_check)).failed:
    print "  ################################"
    print "  ################################"
    print "    REGEX CHECK FAILED!!"
    print "  ################################"
    print "  ################################"
    if notifications_email:
      local("echo 'Your regex check for the URL %s  with string check for '%s' has failed, the site may be down. Please check it immediately!' | mail -s 'Site down following deploy' %s" % (url_to_check, string_to_check, notifications_email))
      print "===> Sent warning email to %s" % notifications_email
  else:
    print "===> Site is up"