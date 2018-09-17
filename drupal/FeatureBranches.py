from fabric.api import *
from fabric.contrib.files import sed
import string
# Custom Code Enigma modules
import DrupalUtils
import Drupal


httpauth_pass = None
ssl_enabled = False
ssl_ip = None
ssl_cert = None
drupal_common_config = None


# Feature branches only, preparing database
# Assumes single server, cannot work on a cluster
@task
def initial_db_and_config(repo, branch, build, site, import_config, drupal_version):
  with settings(warn_only=True):
    # Run database updates
    drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
    if DrupalUtils.drush_command("updatedb", site, drush_runtime_location, True, None, None, True).failed:
      raise SystemExit("###### Could not run database updates! Everything else has been done, but failing the build to alert to the fact database updates could not be run.")
    else:
      Drupal.drush_clear_cache(repo, branch, build, site, drupal_version)

    # Run entity updates
    if drupal_version > 7:
      if DrupalUtils.drush_command("entity-updates", site, drush_runtime_location, True, None, None, True).failed:
        print "###### Could not carry out entity updates! Continuing anyway, as this probably isn't a major issue."

    # Import config
    if drupal_version > 7 and import_config:
      print "===> Importing configuration for Drupal 8 site..."
      if DrupalUtils.drush_command("cim", site, drush_runtime_location, True, None, None, True).failed:
        raise SystemExit("###### Could not import configuration! Failing build.")
      else:
        print "===> Configuration imported. Running a cache rebuild..."
        Drupal.drush_clear_cache(repo, branch, build, site, drupal_version)


# Sets all the variables for a feature branch InitialBuild
@task
def configure_feature_branch(buildtype, config, branch, alias):
  # Set up global variables required in main()
  global httpauth_pass
  global ssl_enabled
  global ssl_ip
  global ssl_cert
  global drupal_common_config
  global featurebranch_url
  global featurebranch_vhost

  featurebranch_url = None
  featurebranch_vhost = None


  # If the buildtype is 'custombranch', which it will be when deploying a custom branch (i.e one
  # that isn't in the normal workflow), we need to make sure the chosen branch *isn't* one from
  # the normal workflow. If it is, the live symlink will be set incorrectly, which will cause
  # the site to not function properly.
  if buildtype == "custombranch":
    print "===> Feature branch, attempting to build branch %s" % branch
    # So, first check if there's a buildtype in the confi.ini file that matches the branch name,
    # because if it does, it means that site already has a build. This check will cover stage and
    # prod builds, mostly.
    if config.has_section(branch):
      print "===> You cannot build the %s site using the custom branch job as this will cause the live symlink to be incorrect. Aborting." % branch
      raise ValueError("You cannot build the %s site using the custom branch job as this will cause the live symlink to be incorrect. Aborting." % (branch))

    # There will be cases where there isn't a buildtype in config.ini for $branch. At CE, we use
    # master -> stage -> prod branch workflow, but use the [dev] buildtype in config.ini. So this
    # next check will check for the branch name provided in a small list of branch names. If found
    # abort the build.
    else:
      cannot_build = ['dev', 'master', 'stage', 'prod']
      if branch in cannot_build:
        print "===> You cannot build the %s site using the custom branch job as this will cause the live symlink to be incorrect. Aborting." % branch
        raise ValueError("You cannot build the %s site using the custom branch job as this will cause the live symlink to be incorrect. Aborting." % (branch))
      else:
        # If the feature branch can be built (i.e it isn't a branch that is in the normal workflow)
        # we can search for and set some options for use during the initial build.
        if config.has_section("featurebranch"):
          print "[featurebranch] section found. Check for certain options next."
          # Check if there's an httpauth option under the [featurebranch] section. If there is, set
          # the httpauth_pass variable to that value. That will be used later in the initial_build()
          # function.
          if config.has_option("featurebranch", "httpauth"):
            print "Feature Branch: Found a httpauth option..."
            httpauth_pass = config.get("featurebranch", "httpauth")

          # Check if there's an ssl option under the [featurebranch] section. If there is, set the
          # ssl_enabled variable to that value (it must be True or False)
          if config.has_option("featurebranch", "ssl"):
            print "Feature Branch: Found a ssl option..."
            ssl_enabled = config.getboolean("featurebranch", "ssl")

            if ssl_enabled:
              # If ssl is enabled, check that the sslname option has been set. This is required to
              # inform Jenkins of the SSL certificate and key to check for during the initial build
              # and if it exists, use it in the vhost.
              # If this option does not exist and ssl is enabled, abort the build. Currently, the
              # 'sslname' option HAS to be set in config.ini.
              if config.has_option("featurebranch", "sslname"):
                ssl_cert = config.get("featurebranch", "sslname")
              else:
                print "===> Currently, the SSL certificate and key must exist on the server, so you must set the 'sslname' option to the name of the file, such as 'wildcard.company.net'. *DO NOT* include the .key or .crt extensions. As a result of the sslname option not being set, we must abort this build."
                raise ValueError("Currently, the SSL certificate and key must exist on the server, so you must set the 'sslname' option to the name of the file, such as 'wildcard.company.net'. *DO NOT* include the .key or .crt extensions. As a result of the sslname option not being set, we must abort this build.")

              if config.has_option("featurebranch", "sslip"):
                ssl_ip = config.get("featurebranch", "sslip")

          # Check if there's a url option under the [featurebranch] section. If there is, set
          # the url variable to that value, which will override the default None value.
          if config.has_option("featurebranch", "urltemplate"):
            print "Feature Branch: Found a urltemplate option..."
            urltemplate = config.get("featurebranch", "urltemplate")
            urltemplate = urltemplate.replace("reponame", alias, 1)
            urltemplate = urltemplate.replace("branchname", branch, 1)
            print "urltemplate is now %s" % urltemplate
            featurebranch_url = urltemplate

          if config.has_option("featurebranch", "drupalcommonconfig"):
            print "Feature Branch: Found a drupalcommonconfig option..."
            drupal_common_config = config.get("featurebranch", "drupalcommonconfig")
            print "Feature Branch: drupal_common_config is now %s" % drupal_common_config

          if config.has_option("featurebranch", "vhost"):
            print "Feature branch: Found a vhost option..."
            featurebranch_vhost = config.get("featurebranch", "vhost")
            print "Feature Branch: featurebranch_vhost is now %s" % featurebranch_vhost
        else:
          print "We could not find a [featurebranch] section in the config.ini file, yet this *is* a feature branch build. That is perfectly fine, as options do not need to be set for a feature branch build, but they can be handy."


# Used to configure the mapping of sites to teardown, in case of a multisite setup
@task
def configure_teardown_mapping(repo, branch, buildtype, config_filename, mapping):
  with settings(warn_only=True):
    buildtype_config_filename = buildtype + '.' + config_filename
    if run("stat /var/www/live.%s.%s/%s" % (repo, branch, buildtype_config_filename)).succeeded:
      config_filename = buildtype_config_filename
    else:
      if run("stat /var/www/live.%s.%s/%s" % (repo, branch, config_filename)).failed:
        raise SystemExit("Could not find any kind of config.ini file on the server the site is been torn down from. Failing the teardown build.")

    config_filepath = "/var/www/live.%s.%s/%s" % (repo, branch, config_filename)

    if run("grep \"\[Sites\]\" %s" % config_filepath).return_code != 0:
      print "###### Didn't find a [Sites] section in %s, so assume this is NOT a multisite build. In which case, we just need to teardown the default site."
      mapping.update({repo:"default"})
      return mapping
    else:
      list_of_sites = run("grep \"sites=\" %s | cut -d= -f2" % config_filepath)
      for each_site in list_of_sites.split(','):
        if each_site == 'default':
          alias = repo
        else:
          alias = "%s_%s" % (repo, each_site)
        mapping.update({alias:each_site})

      print "Final mapping is: %s" % mapping
      return mapping


# Used for Drupal build teardowns.
@task
def remove_site(repo, branch, alias, site, mysql_config):
  # Drop DB...
  # 'build' and 'buildtype' can be none because only needed for revert which isn't relevant
  drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)
  drush_output = Drupal.drush_status(repo, branch, None, None, site, drush_runtime_location)
  dbname = Drupal.get_db_name(repo, branch, None, None, site, drush_output)

  # If the dbname variable is still empty, fail the build early
  if not dbname:
    raise SystemExit("###### Could not determine the database name, so we cannot proceed with tearing down the site.")

  print "===> Dropping database and user: %s" % dbname
  sudo("mysql --defaults-file=%s -e 'DROP DATABASE IF EXISTS `%s`;'" % (mysql_config, dbname))
  sudo("mysql --defaults-file=%s -e \"DROP USER \'%s\'@\'localhost\';\"" % (mysql_config, dbname))

  with settings(warn_only=True):
    # Remove files directories
    print "===> Removing files directories..."
    sudo("rm -rf /var/www/shared/%s_%s_*" % (alias, branch))

    # Remove shared settings file
    print "===> Removing settings.inc file..."
    sudo("rm /var/www/config/%s_%s.settings.inc" % (alias, branch))


@task
def remove_drush_alias(alias, branch):
  with settings(warn_only=True):
    print "===> Removing drush alias..."
    sudo("rm /etc/drush/%s_%s.alias.drushrc.php" % (alias, branch))
