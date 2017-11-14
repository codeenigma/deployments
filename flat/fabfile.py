from fabric.api import *
from fabric.contrib.files import exists
import os
import sys
import random
import string
import ConfigParser
# Custom Code Enigma modules
import common.ConfigFile
import common.Utils
import Flat
# Needed to get variables set in modules back into the main script
from common.ConfigFile import *
from common.Utils import *

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Read the config.ini file from repo, if it exists
config = common.ConfigFile.read_config_file()


@task
def main(repo, repourl, branch, build, buildtype, symassets="nosym", keepbuilds=10, cluster=False):
  # Set our host_string based on user@host
  user = 'jenkins'

  # Define primary host
  common.Utils.define_host(config, buildtype, repo)

  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster)

  # Didn't find any host in the map for this project.
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  env.host_string = '%s@%s' % (user, env.host)

  # Let's allow developers to perform some pre-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

  common.Utils.clone_repo(repo, repourl, branch, build)
  common.Utils.adjust_live_symlink(repo, branch, build)
  if symassets == "sym":
    Flat.symlink_assets(repo, branch, build)

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

  common.Utils.remove_old_builds(repo, branch, keepbuilds)
