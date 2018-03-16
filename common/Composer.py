from fabric.api import *
from fabric.operations import put
from fabric.contrib.files import *
import random
import string


# Run a composer command
@task
@roles('app_all')
def composer_command(site_root, composer_command="install", package_to_install=False, install_no_dev=True, composer_lock=True, composer_global=False, composer_sudo=False):
  this_command = ""
  if composer_sudo:
    this_command = "sudo composer "
  else:
    this_command = "composer "

  if composer_global:
    this_command = this_command + "global "

  this_command = this_command + composer_command

  if composer_command == "install" and install_no_dev:
    this_command = this_command + " --no-dev"
  elif composer_command == "install" and not install_no_dev:
    this_command = this_command + " --dev"

  if package_to_install:
    this_command = this_command + " " + package_to_install

  # Sometimes we will want to remove composer.lock prior to installing
  with settings(warn_only=True):
    if not composer_lock:
      print "===> Removing composer.lock prior to attempting an install"
      sudo("rm %s/composer.lock" % site_root)
      sudo("rm -R %s/vendor" % site_root)

  with cd(site_root):
    print "===> Running the composer command `%s` in the directory %s" % (this_command, site_root)
    run(this_command)
