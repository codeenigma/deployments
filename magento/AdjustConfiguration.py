from fabric.api import *
from fabric.contrib.files import *
import random
import string

# Adjust shared files symlink
def adjust_files_symlink(repo, environment, build, url, static_dir):
  # Work out if our codebase is in the 'www' subdirectory (normal) or not (Acquia?)
  with settings(hide('warnings', 'stderr'), warn_only=True):
    if run("stat /var/www/%s_%s_%s/www" % (repo, environment, build)).return_code == 0:
      www_subdir = "www"
    elif run("stat /var/www/%s_%s_%s/docroot" % (repo, environment, build)).return_code == 0:
      www_subdir = "docroot"
    else:
      www_subdir = "."

  print "===> Setting the symlink for files"
  magento_subdir = run('grep MAGENTO_SUBDIR /var/www/%s_%s_%s/README.txt | cut -d\= -f2 | head -1' % (repo, environment, build))
  if magento_subdir == ".":
    sudo("ln -s /var/www/shared/%s_magento_%s_pub/media /var/www/%s_%s_%s/%s/pub/media" % (repo, environment, repo, environment, build, www_subdir))
    if static_dir == "shared":
      sudo("ln -s /var/www/shared/%s_magento_%s_pub/static /var/www/%s_%s_%s/%s/pub/static" % (repo, environment, repo, environment, build, www_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_var/ /var/www/%s_%s_%s/%s/var" % (repo, environment, repo, environment, build, www_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_etc/config.php /var/www/%s_%s_%s/%s/app/etc/config.php" % (repo, environment, repo, environment, build, www_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_etc/env.php /var/www/%s_%s_%s/%s/app/etc/env.php" % (repo, environment, repo, environment, build, www_subdir))
  else:
    sudo("ln -s /var/www/shared/%s_magento_%s_pub/media /var/www/%s_%s_%s/%s/%s/pub/media" % (repo, environment, repo, environment, build, www_subdir, magento_subdir))
    if static_dir == "shared":
      sudo("ln -s /var/www/shared/%s_magento_%s_pub/static /var/www/%s_%s_%s/%s/%s/pub/static" % (repo, environment, repo, environment, build, www_subdir, magento_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_var/ /var/www/%s_%s_%s/%s/%s/var" % (repo, environment, repo, environment, build, www_subdir, magento_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_etc/config.php /var/www/%s_%s_%s/%s/%s/app/etc/config.php" % (repo, environment, repo, environment, build, www_subdir, magento_subdir))
    sudo("ln -s /var/www/shared/%s_magento_%s_etc/env.php /var/www/%s_%s_%s/%s/%s/app/etc/env.php" % (repo, environment, repo, environment, build, www_subdir, magento_subdir))
  if static_dir == "unshared":
    with cd("/var/www/%s_%s_%s/%s/%s" % (repo, environment, build, www_subdir, magento_subdir)):
      sudo("php bin/magento setup:static-content:deploy")
      sudo("chown -R jenkins:jenkins /var/www/%s_%s_%s/%s/%s/pub/static" % (repo, environment, build, www_subdir, magento_subdir))
      sudo("chown -R www-data:www-data /var/www/%s_%s_%s/%s/%s/pub/static/_requirejs" % (repo, environment, build, www_subdir, magento_subdir))
      sudo("chown -R www-data:www-data /var/www/shared/%s_magento_%s_var" % (repo, environment))