from fabric.api import *
import Drupal
from Drupal import *


# Function to export site config
@task
@roles('app_primary')
def config_export(repo, branch, build, drupal_version):
  if drupal_version == '8':
    print "===> Executing hook: config_export"
    print "===> Exporting site config, which will be downloadable"
    with settings(warn_only=True):
      print "First see if the directory /var/www/shared/%s_%s_exported_config exists." % (repo, branch)
      if run("stat /var/www/shared/%s_%s_exported_config" % (repo, branch)).return_code == 0:
        print "Exported config directory exists. Remove its contents"
        if sudo("rm -r /var/www/shared/%s_%s_exported_config" % (repo, branch)).failed:
          print "Warning: Cannot remove old exported config. Stop exporting, but proceed with rest of the build"
        else:
          print "Exporting config"
          sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_exported_config" % (repo, branch))
          if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/default && drush -y cex --destination=/var/www/shared/%s_%s_exported_config" % (repo, branch, build, repo, branch)).failed:
            print "Warning: Cannot export config. Stop exporting, but proceed with rest of the build"
          else:
            print "Exported config successfully. It will be available at /var/www/shared/%s_%s_exported_config" % (repo, branch)
