from fabric.api import *
from fabric.contrib.files import sed
import os


# Builds the variables needed to carry out Behat testing later
@task
def prepare_behat_tests(config, buildtype):
  # We only want to run Behat tests if run_tests in config.ini is set to True
  behat_tests = False
  behat_junit = False
  behat_buildtypes = []
  behat_tags = []
  behat_modules = []
  behat_config = None

  # Check the run_tests option is present
  if config.has_option("Behat", "run_tests"):
    behat_tests = config.getboolean("Behat", "run_tests")

  if behat_tests:
    if config.has_option("Behat", "test_buildtypes"):
      test_buildtypes = config.get("Behat", "test_buildtypes")
      test_buildtypes = test_buildtypes.split(',')
      for each_buildtype in test_buildtypes:
        each_buildtype = each_buildtype.strip()
        behat_buildtypes.append(each_buildtype)
  else:
    behat_buildtypes = ['master', 'dev', 'stage', 'develop']

  if config.has_option("Behat", "junit"):
    behat_junit = config.getboolean("Behat", "junit")

  if config.has_option("Behat", "tags_%s" % buildtype):
    test_tags = config.get("Behat", "tags_%s" % buildtype)
    test_tags = test_tags.split(',')
    for each_tag in test_tags:
      each_tag = each_tag.strip()
      behat_tags.append(each_tag)

  if config.has_option("Behat", "disable_modules"):
    disable_modules = config.get("Behat", "disable_modules")
    disable_modules = disable_modules.split(',')
    for each_module in disable_modules:
      each_module = each_module.strip()
      behat_modules.append(each_module)

  behat_config = {
    'behat_tests': behat_tests,
    'behat_junit': behat_junit,
    'behat_buildtypes': behat_buildtypes,
    'behat_tags': behat_tags,
    'behat_modules': behat_modules
  }

  return behat_config


# Run tests that were enabled in the config file, if any
@task
@roles('app_primary')
def run_tests(repo, branch, build, config):
  print "===> Running tests..."
  test_types = [ 'simpletest', 'coder' ]
  for test_type in test_types:
    if config.has_section(test_type):
      for option in config.options(test_type):
        if config.getint(test_type, option) == 1:
          script_dir = os.path.dirname(os.path.realpath(__file__))
          if put(script_dir + '/../util/run-tests', '/home/jenkins', mode=0755).failed:
            print "===> Could not copy the test runner script to the application server, tests will not be run"
          else:
            print "===> Test runner script copied to %s:/home/jenkins/run-tests" % env.host
            print "===> We will attempt to run %s against %s" % (test_type, option)
            run("/home/jenkins/run-tests /var/www/%s_%s_%s/www %s %s | tee /tmp/%s.%s.review" % (repo, branch, build, test_type, option, repo, option))
            run('egrep -q "\[normal\]|\[major\]|\[critical\]" /tmp/%s.%s.review && echo "Found errors running test %s!" && exit 1 || exit 0' % (repo, option, option))
    else:
      print "===> Didn't find any tests to run for %s" % test_type


# Run behat tests, if present
@task
@roles('app_primary')
def run_behat_tests(repo, branch, build, alias, buildtype, url, ssl_enabled, junit, drupal_version, tags = [], disable_modules = []):
  cwd = os.getcwd()
  continue_tests = True
  tests_failed = False

  with settings(warn_only=True):
    while continue_tests:
      # Disable modules that enable HTTP auth.
      if disable_modules:
        if drupal_version == '8':
          for module in disable_modules:
            if run("drush @%s_%s -y pm-uninstall %s" % (alias, branch, module)).failed:
              print "Cannot disable %s. Stopping tests early..." % module
              continue_tests = False
              break
        else:
          for module in disable_modules:
            if run("drush @%s_%s -y dis %s" % (alias, branch, module)).failed:
              print "Cannot disable %s. Stopping tests early..." % module
              continue_tests = False
              break

      with cd("/var/www/%s_%s_%s/tests/behat" % (repo, branch, build)):
        run("composer install")

        if run("stat behat.yml").failed:
          # No behat.yml file, so let's move our buildtype specific behat file into place, if it exists.
          if run("stat %s.behat.yml" % buildtype).failed:
            # No buildtype.behat.yml either. In that case, don't run any tests and break out.
            print "No behat.yml or %s.behat.yml file. Stopping tests early..." % buildtype
            continue_tests = False
            break
          else:
            # We found a buildtype.behat.yml file, so move it into place
            print "Found a %s.behat.yml file. Moving it to behat.yml because behat.yml didn't exist." % buildtype
            sudo("mv %s.behat.yml behat.yml" % buildtype)
        else:
          # We found a behat.yml file. Let's see if there's a buildtype.behat.yml file before we move it out of the way.
          if run("stat %s.behat.yml" % buildtype).failed:
            # Didn't find a buildtype.behat.yml file. Nothing else to do.
            print "didn't find a %s.behat.yml file, so we'll use the behat.yml file that was found." % buildtype
          else:
            # We found a buildtype.behat.yml file, so we want to use that. Move the behat.yml file aside so the buildtype specific file can be used.
            print "Found %s.behat.yml, so we'll move behat.yml out of the way." % buildtype
            sudo("mv behat.yml behat.yml.backup")
            sudo("mv %s.behat.yml behat.yml" % buildtype)

        # If buildtype is 'custombranch', this is a feature branch deployment, so there're some special things we need to do.
        if buildtype == "custombranch":
          behat_file = "behat.yml"
          if run("grep \"base_url:\" %s" % behat_file).return_code == 0:
            # The behat.yml file does contain the base_url: string. Let's replace it with the url of our feature site.
            print "Replacing the old base_url value with the URL for the feature branch site..."
            scheme = 'https' if ssl_enabled else 'http'
            replace_string = "base_url: .*"
            replace_with = "base_url: %s://%s" % (scheme, url)
            replace_with = replace_with.lower()
            sed(behat_file, replace_string, replace_with, limit='', use_sudo=False, backup='.bak', flags="i", shell=False)
          else:
            # Seems like the behat.yml file doesn't contain the string we're looking for. Stop performing tests.
            print "It doesn't look like the behat.yml file has the string we're looking for. Stopping tests early..."
            continue_tests = False
            break

        # Now it's time to run the tests...
        print "===> Running behat tests (without Selenium)..."
        if tags:
          test_tags = '&&'.join(tags)
          print "Debug info - test_tags = %s" % test_tags
        else:
          test_tags = '~@javascript'
        if junit:
          test_method = '-f progress -o std -f junit -o xml'
        else:
          test_method = '-f pretty -o std'
        if run("bin/behat -v --tags=\"%s\" %s" % (test_tags, test_method)).failed:
          print "Behat tests seem to have failed!"
          tests_failed = True
        else:
          print "Looks like Behat tests were successful!"

        if junit:
          print "We need to copy the JUnit report to the Jenkins server so it can be processed."
          if sudo("stat /var/www/live.%s.%s/tests/behat/xml/default.xml" % (repo, branch)).failed:
            print "No xml file found in /var/www/live.%s.%s/tests/behat/xml. That's weird, but we'll carry on." % (repo, branch)
          else:
            print "Found an xml in /var/www/live.%s.%s/tests/behat/xml. Going to copy it to the Jenkins server." % (repo, branch)
            local("mkdir -p %s/tests/behat/xml" % cwd)
            if local("scp jenkins@%s:/var/www/live.%s.%s/tests/behat/xml/default.xml %s/tests/behat/xml/" % (env.host, repo, branch, cwd)).failed:
              print "Could not copy JUnit report to Jenkins server. We won't fail the build here, though."
            else:
              print "Copied JUnit report to Jenkins server."


      continue_tests = False
      # End while loop

    # Re-enable modules
    if disable_modules:
      reenable_modules(alias, branch, buildtype, drupal_version, disable_modules)

    # Send test status back to main fabfile
    return tests_failed


@task
def reenable_modules(alias, branch, buildtype, drupal_version, enable_modules = []):
  with settings(warn_only=True):
    if drupal_version == '8':
      if run("drush @%s_%s -y cim" % (alias, branch)).failed:
        print "Cannot import config to enable modules. Manual investigation is required."
      else:
        print "Modules re-enabled via config import."
    else:
      if enable_modules:
        for module in enable_modules:
          if run("drush @%s_%s -y en %s" % (alias, branch, module)).failed:
            print "Cannot enable %s. Manual investigation is required." % module
          else:
            print "%s re-enabled." % module
