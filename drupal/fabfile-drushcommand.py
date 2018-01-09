from fabric.api import *
import os
import sys
import string
import time
# Custom Code Enigma modules
import common.Utils
import Drupal

# Override the shell env variable in Fabric, so that we don't see 
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'


def main(shortname, branch, command, backup=True):
  with settings(warn_only=True):
    if run('drush sa | grep ^@%s_%s$ > /dev/null' % (shortname, branch)).failed:
      raise SystemError("You can't run a command on a site that doesn't exist! Alias @%s_%s not recognised." % (shortname, branch))

  # Take a database backup first if told to.  
  if backup:
    Drupal.backup_db(shortname, branch)

  # Strip nastiness from the command
  command = command.replace(";", "")
  command = command.replace("&&", "")
  command = command.replace("&", "")
  command = command.replace("||", "")
  command = command.replace("|", "")
  command = command.replace("!", "")
  command = command.replace("<", "")
  command = command.replace(">", "")

  print "Command is drush @%s_%s %s" % (shortname, branch, command)

  BLACKLISTED_CMDS = ['sql-drop', 'site-install', 'si', 'sudo', 'rm', 'shutdown', 'reboot', 'halt', 'chown', 'chmod', 'cp', 'mv', 'nohup', 'echo', 'cat', 'tee', 'php-eval', 'variable-set', 'vset']

  for cmd in BLACKLISTED_CMDS:
    if command.startswith(cmd):
      raise SystemError("Surely you jest... I won't run drush @%s_%s %s. Ask a sysadmin instead." % (shortname, branch, command))

  run("drush -y @%s_%s %s" % (shortname, branch, command) )
