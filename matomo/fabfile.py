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
import Matomo
import Revert

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

global config


# Main build script
@task
def main(repo, repourl, build, branch, buildtype, keepbuilds=10, restartvarnish="yes", cluster=False, rds=False, autoscale=None, mysql_config='/etc/mysql/debian.cnf', config_filename='config.ini', config_fullpath=False):

  if config_fullpath == "False":
    config_fullpath = False
  if config_fullpath == "True":
    config_fullpath = True

  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.buildtype_config_file(buildtype, config_filename, fullpath=config_fullpath)

  # Can be set in the config.ini [AWS] section
  aws_credentials = common.ConfigFile.return_config_item(config, "AWS", "aws_credentials", "string", "/home/jenkins/.aws/credentials")
  aws_autoscale_group = common.ConfigFile.return_config_item(config, "AWS", "aws_autoscale_group", "string", "prod-asg-prod")
  aws_package_all_builds = common.ConfigFile.return_config_item(config, "AWS", "aws_package_all_builds", "boolean", False)
  aws_build_tar = common.ConfigFile.return_config_item(config, "AWS", "aws_build_tar", "boolean", True)

  # Now we need to figure out what server(s) we're working with
  # Define primary host
  common.Utils.define_host(config, buildtype, repo)
  # Define server roles (if applicable)
  common.Utils.define_roles(config, cluster, autoscale, aws_credentials, aws_autoscale_group)
  # Check where we're deploying to - abort if nothing set in config.ini
  if env.host is None:
    raise ValueError("===> You wanted to deploy a build but we couldn't find a host in the map file for repo %s so we're aborting." % repo)

  # Set some default config options and variables
  user = "jenkins"
  previous_build = ""
  previous_db = ""
  www_root = "/var/www"
  application_directory = "www"

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  # Can be set in the config.ini [Database] section
  db_name = common.ConfigFile.return_config_item(config, "Database", "db_name")
  db_username = common.ConfigFile.return_config_item(config, "Database", "db_username")
  db_password = common.ConfigFile.return_config_item(config, "Database", "db_password")
  db_backup = common.ConfigFile.return_config_item(config, "Database", "db_backup", "boolean", True)

  # Set SSH key if needed
  # @TODO: this needs to be moved to config.ini for Code Enigma GitHub projects
  if "git@github.com" in repourl:
    ssh_key = "/var/lib/jenkins/.ssh/id_rsa_github"

  # Run the tasks.
  # --------------
  execute(common.Utils.clone_repo, repo, repourl, branch, build, None, ssh_key, hosts=env.roledefs['app_all'])

  # Gitflow workflow means '/' in branch names, need to clean up.
  branch = common.Utils.generate_branch_name(branch)
  print "===> Branch is %s" % branch

  # Let's allow developers to perform some early actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre', build_hook_version="1", hosts=env.roledefs['app_all'])
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='pre-prim', build_hook_version="1", hosts=env.roledefs['app_primary'])

  # Record the link to the previous build
  previous_build = common.Utils.get_previous_build(repo, branch, build)

  execute(Matomo.mysql_backup_db, db_name, build, True)

  with settings(hide('warnings', 'stderr'), warn_only=True):
    # Do Matomo deployment here
    print "Running deployment steps"
    execute(AdjustConfiguration.adjust_config, repo, branch, build, www_root, application_directory)
    execute(AdjustConfiguration.adjust_tmp_symlink, repo, branch, build, www_root, application_directory)

    # Let's allow developers to perform some actions right after Matomo is built
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid', build_hook_version="1", hosts=env.roledefs['app_all'])
    execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='mid-prim', build_hook_version="1", hosts=env.roledefs['app_primary'])

    execute(Matomo.database_updates, repo, branch, build, www_root, application_directory, db_name)
  
  # Adjust the live symlink now that all sites have been deployed. Bring them online after this has happened.
  if previous_build is not None:
    execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])

  # This will revert the database if fails
  live_build = run("readlink %s/live.%s.%s" % (www_root, repo, branch))
  this_build = "%s/%s_%s_%s" % (www_root, repo, branch, build)
  # The above paths should match - something is wrong if they don't!
  if not this_build == live_build:
    # Make sure the live symlink is pointing at the previous working build.
    Revert.mysql_revert_db(db_name, build)
    raise SystemExit("####### Could not successfully adjust the symlink pointing to the build! Could not take this build live. Database may have had updates applied against the newer build already. Reverting database")

  execute(Matomo.clear_cache, repo, branch, build, www_root, application_directory)
  # Clear the opcache again after the site has been brought online
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])

  # Let's allow developers to perform some post-build actions if they need to
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post', build_hook_version="1", hosts=env.roledefs['app_all'])
  execute(common.Utils.perform_client_deploy_hook, repo, branch, build, buildtype, config, stage='post-prim', build_hook_version="1", hosts=env.roledefs['app_primary'])

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

  #commit_new_db(repo, repourl, url, build, branch)
  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])
  
  print "####### BUILD COMPLETE."
