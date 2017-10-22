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
import common.BuildTeardown
import FeatureBranches


# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
global config
config = common.ConfigFile.read_config_file()


@task
def main(repo, branch, buildtype, url=None, restartvarnish="yes", restartwebserver="yes"):

  global varnish_restart
  global nginx_restart
  varnish_restart = restartvarnish
  nginx_restart = restartwebserver
  webserver = common.Services.determine_webserver()

  # If the buildtype is 'custombranch', which it will be when tearing down a custom branch (i.e one
  # that isn't in the normal workflow), we need to make sure the chosen branch *isn't* one from
  # the normal workflow.
  if buildtype == "custombranch":
    # So, first check if there's a buildtype in the confi.ini file that matches the branch name,
    # because if it does, it means that site is part of the normal worklow. This check will cover
    # stage and prod builds, mostly.
    if config.has_section(branch):
      print "===> You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % branch
      raise ValueError("You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % (branch))
      
    # There will be cases where there isn't a buildtype in config.ini for $branch. At CE, we use
    # master -> stage -> prod branch workflow, but use the [dev] buildtype in config.ini. So this
    # next check will check for the branch name provided in a small list of branch names. If found
    # abort the build.
    else:
      cannot_build = ['dev', 'develop', 'master', 'stage', 'prod', 'test', 'testing']
      if branch in cannot_build:
        print "===> You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % branch
        raise ValueError("You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % (branch))

  user = "jenkins"

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # If this is Gitflow we need to remove slashes from branch names before continuing
  branch = branch.replace('/', '-')

  # Set a URL if one wasn't already provided
  if url is None:
    url = "%s.%s.%s" % (repo, branch, env.host)

  # Check that the site actually exists before proceeding
  with settings(warn_only=True):
    if run('drush sa | grep \'^@\?%s_%s$\' > /dev/null' % (repo, branch)).failed:
      print "===> The %s site does not exist on the server, so there is nothing to tear down. Aborting." % branch
      raise SystemError("The %s site does not exist on the server, so there is nothing to tear down. Aborting." % branch)

  # Run the tasks.
  # --------------
  # If this is the first build, attempt to install the site for the first time.
  try:
    FeatureBranches.remove_site(repo, branch)
    common.BuildTeardown.remove_vhost(repo, branch, webserver)
    common.BuildTeardown.remove_http_auth(repo, branch, webserver)
    FeatureBranches.remove_drush_alias(repo, branch)
    common.BuildTeardown.remove_cron(repo, branch)

  except:
    e = sys.exc_info()[1]
    raise SystemError(e)

  with settings(hide('warnings', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd', 'nginx', 'varnish']
    for service in services:
      common.Services.clear_php_cache()
      if nginx_restart == 'yes':
        common.Services.reload_webserver()
      if varnish_restart == 'yes':
        common.Services.clear_varnish_cache()
