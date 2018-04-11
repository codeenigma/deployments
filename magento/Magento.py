from fabric.api import *
import os
import sys
import random
import string
import datetime

# Generate a crontab for running magento2's cron on this site
@task
@roles('app_all')
def generate_magento_cron(repo, buildtype):
  if exists("/etc/cron.d/%s_%s_magento_cron" % (repo, buildtype)):
    print "===> Cron already exists, moving along"
  else:
    print "===> No cron job, creating one now"
    now = datetime.datetime.now()
    sudo("touch /etc/cron.d/%s_%s_magento_cron" % (repo, buildtype))
    append_string = """*/%s * * * * www-data   php /var/www/live.%s.%s/www/bin/magento cron:run
*/%s * * * * www-data   php /var/www/live.%s.%s/update/cron.php
*/%s * * * * www-data   php /var/www/live.%s.%s/www/bin/magento setup:cron:run""" % (now.minute, repo, buildtype, now.minute, repo, buildtype, now.minute, repo, buildtype)
    append("/etc/cron.d/%s_%s_magento_cron" % (repo, buildtype), append_string, use_sudo=True)
    print "===> New Magento cron job created at /etc/cron.d/%s_%s_magento_cron" % (repo, buildtype)


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


# Run di:compile and static-content:deploy Magento steps
@task
@roles('app_all')
def magento_compilation_steps(repo, buildtype, build):
  with cd("/var/www/%s_%s_%s/www" % (repo, buildtype, build)):
    sudo("chown -R jenkins:jenkins /var/www/%s_%s_%s/www/pub/static" % (repo, buildtype, build))
    with settings(hide('warnings', 'running', 'stdout', 'stderr'), warn_only=True):
      if run("stat /var/www/%s_%s_%s/www/generated" % (repo, buildtype, build)).return_code == 0:
        sudo("chown -R jenkins:jenkins /var/www/%s_%s_%s/www/generated" % (repo, buildtype, build))
      if run("stat /var/www/%s_%s_%s/www/var/generated" % (repo, buildtype, build)).return_code == 0:
        sudo("chown -R jenkins:jenkins /var/www/%s_%s_%s/www/var/generated" % (repo, environment, build))
    # Run compile and static gen steps
    # Weird - apaprently at this point the var dir is chmod 755 again instead of 2775 as above. Set it back to 2775.
    sudo("chmod 2775 /var/www/%s_%s_%s/www/var" % (repo, buildtype, build))
    run("php bin/magento setup:di:compile")
    run("php bin/magento setup:static-content:deploy")


# Magento maintenance mode tasks
@task
@roles('app_all')
def magento_maintenance_mode(repo, buildtype, build, mode):
  with cd("/var/www/%s_%s_%s/www" % (repo, buildtype, build)):
    sudo("php bin/magento maintenance:%s" % mode)
    if mode == 'disable':
      # Fix up permissions to make www-data happy
      with settings(hide('stdout', 'running', 'stderr'), warn_only=True):
        # cache dir
        sudo("chown -R www-data:www-data /var/www/%s_%s_%s/www/var/page_cache" % (repo, buildtype, build))
        sudo("chown -R www-data:www-data /var/www/%s_%s_%s/www/var/cache" % (repo, buildtype, build))
        sudo("chown -R www-data.www-data /var/www/%s_%s_%s/www/var/di" % (repo, buildtype, build))
        sudo("chown -R www-data.www-data /var/www/%s_%s_%s/www/var/generation" % (repo, buildtype, build))


# Magento database routines
@task
@roles('app_all')
def magento_database_updates(repo, buildtype, build):
  with cd("/var/www/%s_%s_%s/www" % (repo, buildtype, build)):
    sudo("php bin/magento cache:flush")
    sudo("php bin/magento setup:upgrade --keep-generated")
    sudo("php bin/magento setup:di:compile")
    # Fix up permissions to make www-data happy
    with settings(hide('stdout', 'running', 'stderr'), warn_only=True):
      # cache dir
      sudo("chown -R www-data:www-data /var/www/%s_%s_%s/www/var/page_cache" % (repo, buildtype, build))
      sudo("chown -R www-data:www-data /var/www/%s_%s_%s/www/var/cache" % (repo, buildtype, build))
