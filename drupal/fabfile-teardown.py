from fabric.api import *
from fabric.contrib.files import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.Services
import common.Utils
import common.BuildTeardown
import FeatureBranches


# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'


@task
def main(repo, branch, buildtype, alias=None, url=None, restartvarnish="yes", restartwebserver="yes", mysql_config='/etc/mysql/debian.cnf', config_filename="config.ini", config_fullpath=False):
  if alias is None:
    alias = repo

  if config_fullpath == "False":
    config_fullpath = False
  if config_fullpath == "True":
    config_fullpath = True

  global varnish_restart
  global nginx_restart
  varnish_restart = restartvarnish
  nginx_restart = restartwebserver
  webserver = common.Services.determine_webserver()

  # If this is Gitflow we need to remove slashes from branch names before continuing
  branch = branch.replace('/', '-')

  # If the buildtype is 'custombranch', which it will be when tearing down a custom branch (i.e one
  # that isn't in the normal workflow), we need to make sure the chosen branch *isn't* one from
  # the normal workflow.
  if buildtype == "custombranch":
    # There will be cases where there isn't a buildtype in config.ini for $branch. At CE, we use
    # master -> stage -> prod branch workflow, but use the [dev] buildtype in config.ini. So this
    # next check will check for the branch name provided in a small list of branch names. If found
    # abort the build.
    cannot_build = ['dev', 'develop', 'master', 'stage', 'prod', 'test', 'testing']
    if branch in cannot_build:
      print "===> You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % branch
      raise ValueError("You cannot tear down the %s site using the custom branch job as this site is part of the normal workflow. Aborting." % (branch))

  user = "jenkins"

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)
  
  does_exist = common.Utils.get_previous_build(repo, branch, None)

  if does_exist is None:
    raise SystemError("The %s site does not exist on the server, so there is nothing to tear down. Aborting." % branch)

  mapping = {}
  mapping = FeatureBranches.configure_teardown_mapping(repo, branch, buildtype, config_filename, config_fullpath, mapping)

  for alias,site in mapping.iteritems():

    print "===> Removing site %s" % site

    # Run the tasks.
    # --------------
    # If this is the first build, attempt to install the site for the first time.
    try:
      FeatureBranches.remove_site(repo, branch, alias, site, mysql_config)
      common.BuildTeardown.remove_vhost(repo, branch, webserver, alias)
      common.BuildTeardown.remove_http_auth(repo, branch, webserver, alias)
      FeatureBranches.remove_drush_alias(alias, branch)
      common.BuildTeardown.remove_cron(repo, branch, alias)

    except:
      e = sys.exc_info()[1]
      raise SystemError(e)

  common.BuildTeardown.remove_repo_code(repo, branch)

  with settings(hide('warnings', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd', 'nginx', 'varnish']
    for service in services:
      common.Services.clear_php_cache()
      if nginx_restart == 'yes':
        common.Services.reload_webserver()
      if varnish_restart == 'yes':
        common.Services.clear_varnish_cache()
