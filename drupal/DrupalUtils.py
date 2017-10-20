from fabric.api import *
import common.ConfigFile


# Determine which Drupal version is being used
@task
def determine_drupal_version(drupal_version, repo, branch, build, config, method="deployment"):
  # If this is a normal deployment (deployment), use the build number path. If this is a sync (sync), use the live symlink path.
  if method == "sync":
    drupal_path = "/var/www/live.%s.%s" % (repo, branch)
  else:
    drupal_path = "/var/www/%s_%s_%s" % (repo, branch, build)

  # Check to see if Drupal version is specified in config file
  if config.has_section("Version"):
    print "===> Fetching version from config.ini"
    if config.has_option("Version", "drupal_version"):
      drupal_version = config.get("Version", "drupal_version")

  # If no version specified, we'll have to detect it
  if drupal_version is None:
    print "===> No drupal_version override in config.ini, so we'll figure out the version of Drupal ourselves"

    if run("cd %s/www && drush st | grep 'Drupal version'" % drupal_path).failed:
      raise SystemExit("Could not determine Drupal version from drush st. If you're using composer, you MUST override this check in the config.ini file with the [Version] section. Please raise a ticket in Redmine if you're not sure how to do this.")
    else:
      drupal_version = run("cd %s/www && drush st | grep \"Drupal version\" | cut -d\: -f2 | cut -d. -f1" % drupal_path)
      drupal_version = drupal_version.strip()

  print "===> Drupal version is D%s." % drupal_version
  return drupal_version
