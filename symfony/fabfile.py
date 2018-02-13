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
import AdjustConfiguration
import Symfony
import InitialBuild
# Needed to get variables set in modules back into the main script
from common.ConfigFile import *
from common.Utils import *
from Symfony import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
global config
config = common.ConfigFile.read_config_file()


@task
def main(repo, repourl, branch, build, buildtype, siteroot, keepbuilds=10, buildtype_override=False, ckfinder=False, keepbackup=False, migrations=False, cluster=False, with_no_dev=True):

  user = 'jenkins'

  # Set SSH key if needed
  ssh_key = None
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

  # Define primary host
  common.Utils.define_host(config, buildtype, repo)

  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster)

  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Check if we have an alternative buildtype to use for console environment
  # If someone wants to override this, we can pass "dev" as buildtype_override above
  if buildtype_override:
    console_buildtype = buildtype_override
  else:
    console_buildtype = buildtype

  # Let's allow developers to perform some early actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, buildtype, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

  with settings(warn_only=True):
    if run("stat /var/www/config/%s_%s.parameters.yml" % (repo, console_buildtype)).failed:
      # Initial build
      execute(InitialBuild.initial_config, repo, buildtype, build)
      # Let's allow developers to perform some post-initial-build actions if they need to
      execute(common.Utils.perform_client_deploy_hook, repo, buildtype, build, buildtype, config, stage='post-initial', hosts=env.roledefs['app_all'])
    else:
      if keepbackup:
        execute(Symfony.backup_db, repo, console_buildtype, build)

  execute(common.Utils.clone_repo, repo, repourl, branch, build, buildtype, ssh_key, hosts=env.roledefs['app_all'])
  symfony_version = Symfony.determine_symfony_version(repo, buildtype, build)
  print "===> Checking symfony_version: %s" % symfony_version
  execute(Symfony.update_resources, repo, buildtype, build)
  # Only Symfony3 or higher uses the 'var' directory for cache, sessions and logs
  if symfony_version != "2":
    execute(Symfony.symlink_resources, repo, buildtype, build)
  if ckfinder:
    execute(Symfony.symlink_ckfinder_files, repo, buildtype, build)
  execute(Symfony.set_symfony_env, repo, buildtype, build, console_buildtype)
  # Do not use console_buildtype here, we desire a different parameters.yml in shared for each env
  execute(AdjustConfiguration.adjust_parameters_yml, repo, buildtype, build)

  # Let's allow developers to perform some actions right after the app is built
  execute(common.Utils.perform_client_deploy_hook, repo, buildtype, build, buildtype, config, stage='mid', hosts=env.roledefs['app_all'])

  # Only run composer if there is no vendor directory
  with settings(warn_only=True):
    if run("stat /var/www/%s_%s_%s/vendor" % (repo, buildtype, build)).failed:
      # Generally we want to run as prod because dev just enables developer tools
      # If someone wants to override this, we can pass "dev" as buildtype_override above
      execute(Symfony.composer_install, repo, buildtype, build, console_buildtype, with_no_dev)
  if migrations:
    execute(Symfony.run_migrations, repo, buildtype, build, console_buildtype)

  if ckfinder:
    execute(Symfony.ckfinder_install, repo, buildtype, build, console_buildtype)

# Probably obsolete, parameters_BUILDTYPE.yml files should autoload
# @TODO: delete post testing
#  update_local_parameters(repo, buildtype, build)

  execute(Symfony.clear_cache, repo, buildtype, build, console_buildtype)
  # @TODO - this is Drupal specific. Oops!
  execute(common.Utils.adjust_live_symlink, repo, branch, build, buildtype, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, buildtype, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, buildtype, hosts=env.roledefs['app_all'])
