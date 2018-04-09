from fabric.api import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.Utils
import common.MySQL


# Stuff to do when this is the initial build of a Magento site
@task
@roles('app_all')
def initial_magento_build(repo, url, buildtype, build, shared_static_dir, config, rds, db_name, db_username, mysql_version, db_password, mysql_config, dump_file):
  print "===> This looks like the first build! We have some things to do.."

  print "===> Making the Magento shared files dir and setting symlink"
  #pub
  sudo("mkdir -p /var/www/shared/%s_magento_%s_pub/{media,static}" % (repo, buildtype))
  sudo("chown -R jenkins.www-data /var/www/shared/%s_magento_%s_pub" % (repo, buildtype))
  sudo("chmod -R 2770 /var/www/shared/%s_magento_%s_pub" % (repo, buildtype))
  # var
  sudo("mkdir -p /var/www/shared/%s_magento_%s_var" % (repo, buildtype))
  sudo("chown jenkins.www-data /var/www/shared/%s_magento_%s_var" % (repo, buildtype))
  sudo("chmod 2770 /var/www/shared/%s_magento_%s_var" % (repo, buildtype))
  # local.xml dir
  sudo("mkdir -p /var/www/shared/%s_magento_%s_etc" % (repo, buildtype))
  sudo("chown jenkins.www-data /var/www/shared/%s_magento_%s_etc" % (repo, buildtype))
  sudo("chmod 2770 /var/www/shared/%s_magento_%s_etc" % (repo, buildtype))

  sudo("ln -s /var/www/shared/%s_magento_%s_pub/media /var/www/%s_%s_%s/www/pub/media" % (repo, buildtype, repo, buildtype, build))
  if shared_static_dir:
    sudo("ln -s /var/www/shared/%s_magento_%s_pub/static /var/www/%s_%s_%s/www/pub/static" % (repo, buildtype, repo, buildtype, build))
  sudo("ln -s /var/www/shared/%s_magento_%s_var /var/www/%s_%s_%s/www/var" % (repo, buildtype, repo, buildtype, build))

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

  # If we have imported a real database dump, then use the local.xml
  # template for Magento that presumes the Magento site has been 'installed'
  if dump_file:
    # @TODO this template needs adding to the repo and 'putting' in place prior to copy
    run("cp /usr/local/etc/local.xml.template /var/www/%s_%s_%s/www/app/etc/local.xml" % (repo, buildtype, build))
  else:
    # Otherwise, use a slightly different local.xml template which contains
    # the <install> tags commented out. Assume the user will run through
    # the Magento install themselves.
    # @TODO: note, if someone does a 'sync' from prod here, the database will be populated,
    # but the local.xml will still be read as 'uninstalled'. Will need a manual modification
    # of the local.xml to uncomment the <install> tags.
    #
    # @TODO this template needs adding to the repo and 'putting' in place prior to copy
    run("cp /usr/local/etc/local.xml.template.uninstalled /var/www/%s_%s_%s/www/app/etc/local.xml" % (repo, buildtype, build))

  # Replace the dummy database credentials with real ones 
  run("sed -i s/EXAMPLE_USER/%s/g /var/www/%s_%s_%s/www/app/etc/local.xml" % (new_database[1], repo, buildtype, build))
  run("sed -i s/EXAMPLE_PASS/%s/g /var/www/%s_%s_%s/www/app/etc/local.xml" % (new_database[2], repo, buildtype, build))
  run("sed -i s/EXAMPLE_DB/%s/g /var/www/%s_%s_%s/www/app/etc/local.xml" % (new_database[0], repo, buildtype, build))
  run("sed -i s/EXAMPLEDASHBOARD/%s/g /var/www/%s_%s_%s/www/app/etc/local.xml" % (new_database[0], repo, buildtype, build))

  # @TODO: thought we'd done this!? Ask Mig why these aren't links in the shell script...
  # They seem to become links later for future builds
  # var
  sudo("mkdir -p /var/www/%s_%s_%s/www/var" % (repo, buildtype, build))
  sudo("chown jenkins.www-data /var/www/%s_%s_%s/www/var" % (repo, buildtype, build))
  sudo("chmod 2770 /var/www/%s_%s_%s/www/var" % (repo, buildtype, build))
  # media
  sudo("mkdir -p /var/www/%s_%s_%s/www/media" % (repo, buildtype, build))
  sudo("chown jenkins.www-data /var/www/%s_%s_%s/www/media" % (repo, buildtype, build))
  sudo("chmod 2770 /var/www/%s_%s_%s/www/media" % (repo, buildtype, build))
  # etc
  sudo("mkdir -p /var/www/%s_%s_%s/www/etc" % (repo, buildtype, build))
  sudo("chown jenkins.www-data /var/www/%s_%s_%s/www/etc" % (repo, buildtype, build))
  sudo("chmod 2770 /var/www/%s_%s_%s/www/etc" % (repo, buildtype, build))



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
