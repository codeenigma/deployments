from fabric.api import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.MySQL

# Generate a crontab for running magento2's cron on this site
@task
@roles('app_all')
def generate_magento_cron(repo, buildtype):
  print "===> Generating Magento cron for this site if it isn't there already"
  # TODO this script needs handling
  sudo("/usr/local/bin/magento2_cron %s %s" % (repo, buildtype))


# Adjust shared files symlink
@task
@roles('app_all')
def adjust_files_symlink(repo, buildtype, build, url, shared_static_dir):
  print "===> Setting the symlink for files"
  sudo("ln -s /var/www/shared/%s_magento_%s_pub/media /var/www/%s_%s_%s/www/pub/media" % (repo, buildtype, repo, buildtype, build))
  sudo("ln -s /var/www/shared/%s_magento_%s_var/ /var/www/%s_%s_%s/www/var" % (repo, buildtype, repo, buildtype, build))
  sudo("ln -s /var/www/shared/%s_magento_%s_etc/config.php /var/www/%s_%s_%s/www/app/etc/config.php" % (repo, buildtype, repo, buildtype, build))
  sudo("ln -s /var/www/shared/%s_magento_%s_etc/env.php /var/www/%s_%s_%s/www/app/etc/env.php" % (repo, buildtype, repo, buildtype, build))
  if shared_static_dir:
    sudo("ln -s /var/www/shared/%s_magento_%s_pub/static /var/www/%s_%s_%s/www/pub/static" % (repo, buildtype, repo, buildtype, build))
  else:
    with cd("/var/www/%s_%s_%s/www" % (repo, buildtype, build)):
      sudo("php bin/magento setup:static-content:deploy")
      sudo("chown -R jenkins:jenkins /var/www/%s_%s_%s/www/pub/static" % (repo, buildtype, build))
      sudo("chown -R www-data:www-data /var/www/%s_%s_%s/www/pub/static/_requirejs" % (repo, buildtype, build))
      sudo("chown -R www-data:www-data /var/www/shared/%s_magento_%s_var" % (repo, buildtype))
