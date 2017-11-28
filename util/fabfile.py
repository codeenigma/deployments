from fabric.api import *
from fabric.contrib.files import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.Utils

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'


# Helper task for deploying these scripts to a Jenkins server.
@task
def main(jenkins_server=None, scripts_path="/var/lib/jenkins/scripts", branch="master", user="jenkins", ssh_key=None):
  # Check where we're deploying to - abort if no server specified
  env.host = jenkins_server
  if env.host is None:
    raise ValueError("===> You wanted to deploy your build scripts but you didn't specify a target Jenkins server. Aborting.")

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  with settings(warn_only=True):
    if run("stat %s" % scripts_path).failed:
      print "===> Scripts directory %s not present, we'll try and make it" % scripts_path
      if sudo("mkdir -p %s" % scripts_path).failed:
        raise SystemExit("===> Scripts directory %s did not exist and we couldn't make it either. Aborting." % scripts_path)
      else:
        print "===> Ensuring good permissions on new directory %s" % scripts_path
        sudo("chown -R %s:%s %s" % (user, user, scripts_path))
    else:
      print "===> Found our scripts directory at %s" % scripts_path

  if run("stat %s/.git" % scripts_path).failed:
    raise SystemExit("===> Scripts directory %s is not a Git repository. Aborting." % scripts_path)
  else:
    common.Utils._sshagent_run("cd %s; git pull origin %s" % (scripts_path, branch), ssh_key)

  print ("####### BUILD COMPLETE. Branch %s was refreshed on server %s at path %s" % (branch, scripts_path, env.host))