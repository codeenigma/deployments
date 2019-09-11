from fabric.api import *
from fabric.operations import put
from fabric.contrib.files import *
import random
import string
# Custom Code Enigma modules
import common.Utils


# Run a composer command
@task
@roles('app_all')
def composer_command(site_root, composer_command="install", package_to_install=None, install_no_dev=True, composer_lock=True, composer_global=False, composer_sudo=False, symfony_environment=None, through_ssh=False):
  # Make sure no one passed anything nasty from a build hook
  malicious_code = False
  malicious_code = common.Utils.detect_malicious_strings([';', '&&'], composer_command)
  if malicious_code:
    SystemExit("###### Found possible malicious code in the composer_command variable, aborting!")
  if package_to_install:
    malicious_code = common.Utils.detect_malicious_strings([';', '&&'], package_to_install)
  if malicious_code:
    SystemExit("###### Found possible malicious code in the package_to_install variable, aborting!")
  if symfony_environment:
    malicious_code = common.Utils.detect_malicious_strings([';', '&&'], symfony_environment)
  if malicious_code:
    SystemExit("###### Found possible malicious code in the symfony_environment variable, aborting!")

  this_command = "cd %s; " % site_root
  if symfony_environment:
    this_command = this_command + "SYMFONY_ENV=%s " % symfony_environment

  if composer_sudo:
    this_command = this_command + "sudo "

  this_command = this_command + "composer "

  if composer_global:
    this_command = this_command + "global "

  this_command = this_command + composer_command

  if composer_command == "install" and install_no_dev:
    this_command = this_command + " --no-dev --no-interaction"
  elif composer_command == "install" and not install_no_dev:
    this_command = this_command + " --dev --no-interaction"

  if package_to_install:
    this_command = this_command + " " + package_to_install

  # Sometimes we will want to remove composer.lock prior to installing
  if not composer_lock:
    with settings(warn_only=True):
      print "===> Removing composer.lock prior to attempting an install"
      sudo("rm %s/composer.lock" % site_root)
      sudo("rm -R %s/vendor" % site_root)

  print "===> Running the composer command `%s`" % this_command
  if through_ssh:
    # If `through_ssh` is set to True in config.ini, run the Composer command through the _sshagent_run() function, which will allow for the use of private repos during a composer install, for example.
    common.Utils._sshagent_run(this_command)
  else:
    # If `through_ssh` is not set, run the Composer command as normal on the destination server.
    run(this_command)

@task
@roles('app_all')
def composer_validate(site_root, through_ssh):
  validate_command = "cd %s; composer validate --no-check-all --no-check-publish" % site_root
  composer_lock_outdated = False
  with settings(hide('warnings', 'stderr'), warn_only=True):
    if through_ssh:
      composer_validate_output = common.Utils._sshagent_run(validate_command)
    else:
      composer_validate_output = run(validate_command)

    if run("echo \"%s\" | grep 'The lock file is not up to date with the latest changes'" % composer_validate_output).failed:
      print "composer.lock is up to date with composer.json"
    else:
      print "composer.lock is not up to date with the latest changes in composer.json. Mark build as unstable."
      composer_lock_outdated = True

  return composer_lock_outdated
