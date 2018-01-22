from fabric.api import *
from fabric.contrib.files import *
import random
import string
import os
import time


# Run phpunit tests
@task
def run_phpunit_tests(repo, branch, build, group='unit', path='www', phpunit_path='vendor/phpunit/phpunit/phpunit'):
  phpunit_tests_failed=True
  with cd("/var/www/%s_%s_%s" % (repo, branch, build)):
    # Make sure phpunit is available to use
    # We don't want to fail if it's already there
    with settings(warn_only=True):
      run('composer require phpunit/phpunit')

    # Now let's look for a phpunit.xml file to use
    phpunit_xml = False
    with settings(warn_only=True):
      # Usual place to expect phpunit.xml
      if run("find /var/www/%s_%s_%s/phpunit.xml" % (repo, branch, build)).return_code == 0:
        phpunit_xml = "phpunit.xml"
      # For Drupal it might be here
      elif run("find /var/www/%s_%s_%s/www/core/phpunit.xml" % (repo, branch, build)).return_code == 0:
        phpunit_xml = "www/core/phpunit.xml"
      # Doesn't look like there is one, let's look for phpunit's default file
      elif run("find /var/www/%s_%s_%s/phpunit.xml.dist" % (repo, branch, build)).return_code == 0:
        phpunit_xml = "phpunit.xml.dist"
      # Nope, last chance, is there a default one in Drupal?
      elif run("find /var/www/%s_%s_%s/www/core/phpunit.xml.dist" % (repo, branch, build)).return_code == 0:
        phpunit_xml = "www/core/phpunit.xml.dist"

    # Not let's run tests
    if phpunit_xml:
      with cd("/var/www/%s_%s_%s" % (repo, branch, build)):
        with settings(warn_only=True):
          if unit == '' and path == '':
            if run('%s --configuration=%s' % (phpunit_path, phpunit_xml)).failed:
              print "===> PHPUNIT FAILED!"
            else:
              print "===> Unit tests succeeded"
              phpunit_tests_failed=False
          else:
            if run('%s --configuration=%s --group= %s %s' % (phpunit_path, phpunit_xml, group, path)).failed:
              print "===> PHPUNIT FAILED!"
            else:
              print "===> Unit tests succeeded"
              phpunit_tests_failed=False
    else:
      print "===> PHPUNIT FAILED! No phpunit.xml was found so we could not run tests"
      
    return phpunit_tests_failed
