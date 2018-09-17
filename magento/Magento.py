from fabric.api import *
from fabric.contrib.files import *
import os
import sys
import random
import string
import datetime

# Generate a crontab for running magento2's cron on this site
@task
@roles('app_primary')
def generate_magento_cron(repo, buildtype, site_link, autoscale=None):
  if exists("/etc/cron.d/%s_%s_magento_cron" % (repo, buildtype)):
    print "===> Cron already exists, moving along"
  else:
    if autoscale is None:
      print "===> No cron job, creating one now"
      now = datetime.datetime.now()
      sudo("touch /etc/cron.d/%s_%s_magento_cron" % (repo, buildtype))
      append_string = """*/%s * * * * www-data   php %s/www/bin/magento cron:run
*/%s * * * * www-data   php %s/update/cron.php
*/%s * * * * www-data   php %s/www/bin/magento setup:cron:run""" % (now.minute, site_link, now.minute, site_link, now.minute, site_link)
      append("/etc/cron.d/%s_%s_magento_cron" % (repo, buildtype), append_string, use_sudo=True)
      print "===> New Magento cron job created at /etc/cron.d/%s_%s_magento_cron" % (repo, buildtype)
    else:
      print "===> This is an autoscale layout, cron should be handled by another task runner such as Jenkins"


# Adjust shared files symlink
@task
@roles('app_all')
def adjust_files_symlink(repo, buildtype, www_root, site_root, user):
  print "===> Setting the symlink for files"
  sudo("ln -s %s/shared/%s_magento_%s_pub/media %s/www/pub/media" % (www_root, repo, buildtype, site_root))
  # The 'var' directory is not 'shared' due to strange cache behaviour when the 'cache' dir is persistent across builds
  # Instead, only var/log, var/report and var/session are 'shared', but the rest of 'var' is build-specific.
  sudo("ln -s %s/shared/%s_magento_%s_var/log %s/www/var/log" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/session %s/www/var/session" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/report %s/www/var/report" % (www_root, repo, buildtype, site_root))
  # Sort out config files
  with settings(warn_only=True):
    sudo("rm %s/www/app/etc/config.php" % site_root)
  sudo("ln -s %s/shared/%s_magento_%s_etc/config.php %s/www/app/etc/config.php" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_etc/env.php %s/www/app/etc/env.php" % (www_root, repo, buildtype, site_root))
  # Build static assets
  with cd("%s/www" % site_root):
    sudo("php bin/magento setup:static-content:deploy")
    sudo("chown -R %s:%s %s/www/pub/static" % (user, user, site_root))
    sudo("chown -R www-data:www-data %s/www/pub/static" % site_root)
    sudo("chown -R www-data:www-data %s/shared/%s_magento_%s_var" % (www_root, repo, buildtype))


# Run di:compile and static-content:deploy Magento steps
@task
@roles('app_all')
def magento_compilation_steps(site_root, user):
  with cd("%s/www" % site_root):
    # Make sure Jenkins owns Magento for the moment
    sudo("chown -R %s:%s %s/www" % (user, user, site_root))
    # Run compile and static gen steps
    # Weird - apaprently at this point the var dir is chmod 755 again instead of 2775 as above. Set it back to 2775.
    sudo("chmod 2775 %s/www/var" % site_root)
    run("php bin/magento setup:di:compile")
    run("php bin/magento setup:static-content:deploy")
    # Set perms back again
    sudo("chown -R www-data:www-data %s/www" % site_root)


# Magento maintenance mode tasks
@task
@roles('app_all')
def magento_maintenance_mode(site_root, mode):
  with cd("%s/www" % site_root):
    sudo("php bin/magento maintenance:%s" % mode)
    if mode == 'disable':
      # Fix up permissions to make www-data happy
      with settings(hide('stdout', 'running', 'stderr'), warn_only=True):
        # cache dir
        sudo("chown -R www-data:www-data %s/www/var/page_cache" % site_root)
        sudo("chown -R www-data:www-data %s/www/var/cache" % site_root)
        sudo("chown -R www-data.www-data %s/www/var/di" % site_root)
        sudo("chown -R www-data.www-data %s/www/var/generation" % site_root)


# Magento database routines
@task
@roles('app_all')
def magento_database_updates(site_root):
  with cd("%s/www" % site_root):
    sudo("php bin/magento cache:flush")
    sudo("php bin/magento setup:upgrade --keep-generated")
    sudo("php bin/magento setup:di:compile")
    # Fix up permissions to make www-data happy
    with settings(hide('stdout', 'running', 'stderr'), warn_only=True):
      # cache dir
      sudo("chown -R www-data:www-data %s/www/var/page_cache" % site_root)
      sudo("chown -R www-data:www-data %s/www/var/cache" % site_root)
