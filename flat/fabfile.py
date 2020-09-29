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
def main(repo, repourl, branch, build, buildtype, symassets="nosym", keepbuilds=10, url=None, cluster=False, php_ini_file=None, autoscale=None):
  www_root = "/var/www"

  # Set our host_string based on user@host
  user = 'jenkins'

  # Can be set in the config.ini [Build] section
  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")
  notifications_email = common.ConfigFile.return_config_item(config, "Build", "notifications_email")
  # Need to keep potentially passed in 'url' value as default
  url = common.ConfigFile.return_config_item(config, "Build", "url", "string", url)
  php_ini_file = common.ConfigFile.return_config_item(config, "Build", "php_ini_file", "string", php_ini_file)

  # Can be set in the config.ini [AWS] section
  aws_credentials = common.ConfigFile.return_config_item(config, "AWS", "aws_credentials", "string", "/home/jenkins/.aws/credentials")
  aws_autoscale_group = common.ConfigFile.return_config_item(config, "AWS", "aws_autoscale_group", "string", "prod-asg-prod")
  aws_package_all_builds = common.ConfigFile.return_config_item(config, "AWS", "aws_package_all_builds", "boolean", False)
  aws_build_tar = common.ConfigFile.return_config_item(config, "AWS", "aws_build_tar", "boolean", True)

  # Define primary host
  common.Utils.define_host(config, buildtype, repo)

  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster, autoscale, aws_credentials, aws_autoscale_group)

  # Didn't find any host in the map for this project.
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  env.host_string = '%s@%s' % (user, env.host)

  # Check the php_ini_file string isn't doing anything naughty
  malicious_code = False
  malicious_code = common.Utils.detect_malicious_strings([';', '&&'], php_ini_file)
  # Set CLI PHP version, if we need to (someone might want to execute some CLI PHP in a build hook)
  if php_ini_file and not malicious_code:
    run("export PHPRC='%s'" % php_ini_file)

  execute(common.Utils.clone_repo, repo, repourl, branch, build, None, ssh_key, hosts=env.roledefs['app_all'])
  
  # Let's allow developers to perform some pre-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', hosts=env.roledefs['app_all'])

  execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])
  if symassets == "sym":
    execute(Flat.symlink_assets, repo, branch, build)

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', hosts=env.roledefs['app_all'])

  # Unset CLI PHP version if we need to
  if php_ini_file:
    run("export PHPRC=''")

  # If this is autoscale at AWS, let's update the tarball in S3
  if autoscale:
    # In some cases, you may not want to tarball up the builds.
    # For example, when all builds are tarballed up, you can't
    # reliably have multiple builds running for dev and stage
    # as it will cause an error when the contents of /var/www
    # change.
    if aws_build_tar:
      execute(common.Utils.tarball_up_to_s3, www_root, repo, branch, build, autoscale, aws_package_all_builds)
    else:
      print "Don't create a tarball after this build. Assume the tarballing is happening separately, such as in an overnight job."

  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])
