from fabric.api import *
from fabric.contrib.files import *

# Custom Code Enigma modules
import common.ConfigFile
import common.Services
import common.Utils
import common.PHP
import AdjustConfiguration
import Drupal
import DrupalUtils


# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

global config


# Here, an editorial site is a copy of the production site, which hooks into
# the same database and files directory as the production site, but is
# hosted on a different server.
#
# As a result, this script assumes an editorial site already exists. It does
# not handle creating a new editorial site.
#
# This script simply sets up some variables from config.ini, clones down the
# repository, adjusts the settings.php and files symlinks, then adjust the live
# symlink, all on the editorial server. Lastly, it clears opcache and purges
# Varnish cache.
@task
def main(repo, repourl, build, branch, buildtype, keepbuilds=10, config_filename='config.ini'):

  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.buildtype_config_file(buildtype, config_filename)

  # We don't need to define a host, as that should be defined in the Jenkins job (or whatever CI is being used)
  # Define server roles (if applicable)
  common.Utils.define_roles(config, False, None)

  user = "jenkins"
  www_root = "/var/www"
  site_root = www_root + '/%s_%s_%s' % (repo, branch, build)
  site_link = www_root + '/live.%s.%s' % (repo, branch)

  # Set our host_string based on user@host
  env.host_string = '%s@%s' % (user, env.host)

  ssh_key = common.ConfigFile.return_config_item(config, "Build", "ssh_key")

  # Can be set in the config.ini [Drupal] section
  ### @TODO: deprecated, can be removed later
  drupal_version = common.ConfigFile.return_config_item(config, "Version", "drupal_version", "string", None, True, True, replacement_section="Drupal")
  # This is the correct location for 'drupal_version' - note, respect the deprecated value as default
  drupal_version = common.ConfigFile.return_config_item(config, "Drupal", "drupal_version", "string", drupal_version)

  # Can be set in the config.ini [Composer] section
  composer = common.ConfigFile.return_config_item(config, "Composer", "composer", "boolean", True)
  composer_lock = common.ConfigFile.return_config_item(config, "Composer", "composer_lock", "boolean", True)
  no_dev = common.ConfigFile.return_config_item(config, "Composer", "no_dev", "boolean", True)

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

  drupal_version = int(DrupalUtils.determine_drupal_version(drupal_version, repo, branch, build, config))
  print "===> the drupal_version variable is set to %s" % drupal_version

  if drupal_version > 7 and composer is True:
    # Sometimes people use the Drupal Composer project which puts Drupal 8's composer.json file in repo root.
    with settings(warn_only=True):
      if run("find %s/composer.json" % site_root).return_code == 0:
        path = site_root
      else:
        path = site_root + "/www"
    execute(common.PHP.composer_command, path, "install", None, no_dev, composer_lock)

  # Compile a site mapping, which is needed if this is a multisite build
  # Just sets to 'default' if it is not
  mapping = {}
  mapping = Drupal.configure_site_mapping(repo, mapping, config)


  for alias,site in mapping.iteritems():
    execute(AdjustConfiguration.adjust_settings_php, repo, branch, build, buildtype, alias, site)
    execute(AdjustConfiguration.adjust_drushrc_php, repo, branch, build, site)
    execute(AdjustConfiguration.adjust_files_symlink, repo, branch, build, alias, site)

  execute(common.Utils.adjust_live_symlink, repo, branch, build, hosts=env.roledefs['app_all'])

  # Final clean up and run tests, if applicable
  execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])
  execute(common.Services.clear_varnish_cache, hosts=env.roledefs['app_all'])
  execute(common.Utils.remove_old_builds, repo, branch, keepbuilds, hosts=env.roledefs['app_all'])
