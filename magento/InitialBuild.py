from fabric.api import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.MySQL

# Generate shared directories for Magento
@task
@roles('app_all')
def initial_magento_folders(repo, buildtype, www_root, site_root, user):
  print "===> Making the Magento shared files dir and setting symlink"
  # pub/media
  sudo("mkdir -p %s/shared/%s_magento_%s_pub/{media,static}" % (www_root, repo, buildtype))
  sudo("chown -R %s.www-data %s/shared/%s_magento_%s_pub" % (user, www_root, repo, buildtype))
  sudo("chmod -R 2770 %s/shared/%s_magento_%s_pub" % (www_root, repo, buildtype))
  # var/log, var/report and var/session
  sudo("mkdir -p %s/shared/%s_magento_%s_var/{log,report,session}" % (www_root, repo, buildtype))
  sudo("chown %s.www-data %s/shared/%s_magento_%s_var" % (user, www_root, repo, buildtype))
  sudo("chmod 2775 %s/shared/%s_magento_%s_var" % (www_root, repo, buildtype))
  # etc for config files
  sudo("mkdir -p %s/shared/%s_magento_%s_etc" % (www_root, repo, buildtype))
  sudo("chown %s.www-data %s/shared/%s_magento_%s_etc" % (user, www_root, repo, buildtype))
  sudo("chmod 2770 %s/shared/%s_magento_%s_etc" % (www_root, repo, buildtype))

  print "===> Setting up links to first build"
  # pub/static
  run("mkdir -p %s/www/pub/static" % site_root)
  # pub/media (must happen after the pub/static as it creates pub)
  sudo("ln -s %s/shared/%s_magento_%s_pub/media %s/www/pub/media" % (www_root, repo, buildtype, site_root))
  # The 'var' directory is not 'shared' due to strange cache behaviour when the 'cache' dir is persistent across builds
  # Instead, only var/log, var/report and var/session are 'shared', but the rest of 'var' is build-specific.
  run("mkdir -p %s/www/var" % site_root)
  sudo("ln -s %s/shared/%s_magento_%s_var/log %s/www/var/log" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/session %s/www/var/session" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/report %s/www/var/report" % (www_root, repo, buildtype, site_root))
  # app/etc
  run("mkdir -p %s/www/app/etc" % site_root)

  # Now we need to prepare for installation
  with cd("%s/www" % site_root):
    sudo("find var vendor pub/static pub/media app/etc -type f -exec chmod g+w {} \;")
    sudo("find var vendor pub/static pub/media app/etc -type d -exec chmod g+ws {} \;")
  with cd(site_root):
    sudo("chown -R www-data:www-data *")
    sudo("chmod 2775 *")


# Actually install Magento
@task
@roles('app_primary')
def initial_magento_build(repo, repourl, branch, user, url, www_root, site_root, buildtype, build, config, rds, db_name, db_username, mysql_version, db_password, mysql_config, dump_file, magento_password, magento_username, magento_email, magento_firstname, magento_lastname, magento_admin_path, magento_mode, cluster):
  # We can default these to None, mysql_new_database() will sort itself out
  list_of_app_servers = None
  db_host = None

  # For clusters we need to do some extra things
  if cluster:
    # This is the Database host that we need to insert into Drupal settings.php. It is different from the main db host because it might be a floating IP
    db_host = config.get('DrupalDBHost', 'dbhost')
    # Convert a list of apps back into a string, to pass to the MySQL new database function for setting appropriate GRANTs to the database
    list_of_app_servers = env.roledefs['app_all']

  if cluster and config.has_section('AppIPs'):
    list_of_app_servers = env.roledefs['app_ip_all']

  print "===> Preparing the new database"
  new_database = common.MySQL.mysql_new_database(repo, buildtype, rds, db_name, db_host, db_username, mysql_version, db_password, mysql_config, list_of_app_servers, dump_file)

  # Install Magento
  with cd("%s/www" % site_root):
    # We need Jenkins to own the directories for the installation
    sudo("chown -R %s:%s *" % (user, user))
    if not magento_email:
      magento_email = "example@example.com"
    magento_url = 'https://' + url
    if run("php bin/magento setup:install --admin-firstname=%s --admin-lastname=%s --admin-email=%s --admin-user=%s --admin-password=%s --base-url=%s --backend-frontname=%s --db-host=%s --db-name=%s --db-user=%s --db-password=%s --use-rewrites=1 --use-secure=1 --use-secure-admin=1 --cleanup-database"
        % (magento_firstname, magento_lastname, magento_email, magento_username, magento_password, magento_url, magento_admin_path, new_database[3], new_database[0], new_database[1], new_database[2])
        ).failed:
      print "########### Magento install went wrong, aborting!"
    else:
      print "########### Your Magento site is ready!"
      print "===> The admin area URL is %s" % (magento_url + '/' + magento_admin_path)
      print "            username: %s" % (magento_username)
      print "            password: %s" % (magento_password)

    # Now deal with the generated config files

    # Note: this happens on app_primary but if we have a cluster this will be shared with other app servers
    # and the later run of Magento/adjust_files_symlink() will ensure all links are in place.
    sudo("mv app/etc/env.php %s/shared/%s_magento_%s_etc/" % (www_root, repo, buildtype))
    sudo("ln -s %s/shared/%s_magento_%s_etc/env.php app/etc/env.php" % (www_root, repo, buildtype))
    # Deploy Magento
    run("php bin/magento deploy:mode:set %s" % magento_mode)

    # Commit resulting config.php file back to Git
    run("git add -f app/etc/config.php")
    run("git commit -m 'Committing config.php back to Git.'")
    run("git push -u origin %s" % branch)
    # And move it to shared so it is available to potential other app servers
    sudo("mv app/etc/config.php %s/shared/%s_magento_%s_etc/" % (www_root, repo, buildtype))
    sudo("ln -s %s/shared/%s_magento_%s_etc/config.php app/etc/config.php" % (www_root, repo, buildtype))
    # Set perms back to www user
    sudo("chown -R www-data:www-data *")


# Install sample data.
@task
@roles('app_primary')
def initial_build_sample_data(site_root):
  print "===> Installing sample data"
  with cd("%s/www" % site_root):
    run("php bin/magento sampledata:deploy")
    run("php bin/magento setup:upgrade")


# Copy the dummy vhost and change values.
@task
@roles('app_all')
def initial_build_vhost(webserver, repo, buildtype, url):
  # Set up the vhost config
  print "===> Setting up an %s vhost" % webserver
  sudo("cp /etc/%s/sites-available/dummy.conf /etc/%s/sites-available/%s.conf" % (webserver, webserver, url))
  sudo("sed -i s/dummydocroot/'\/var\/www\/live.%s.%s\/www/' /etc/%s/sites-available/%s.conf" % (repo, buildtype, webserver, url))

  # change other dummy values e.g for logs, ServerName
  sudo("sed -i s/dummy/%s.%s/ /etc/%s/sites-available/%s.conf" % (repo, buildtype, webserver, url))
  sudo("sed -i s/example/%s/ /etc/%s/sites-available/%s.conf" % (url, webserver, url))

  # Enable the vhost
  sudo("ln -s /etc/%s/sites-available/%s.conf /etc/%s/sites-enabled/%s.conf" % (webserver, url, webserver, url))
  print "Tidy up and remove the dummy vhosts. Don't fail the build if they can't be removed."
  with settings(warn_only=True):
    sudo("rm /etc/%s/sites-available/dummy*.conf" % webserver)

  url_output = url.lower()
  print "***** Your URL is http://%s *****" % url_output
