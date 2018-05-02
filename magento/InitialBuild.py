from fabric.api import *
import os
import sys
import random
import string
# Custom Code Enigma modules
import common.MySQL
import common.PHP

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
  sudo("chown -R %s:www-data %s/shared/%s_magento_%s_pub" % (user, www_root, repo, buildtype))
  # The 'var' directory is not 'shared' due to strange cache behaviour when the 'cache' dir is persistent across builds
  # Instead, only var/log, var/report and var/session are 'shared', but the rest of 'var' is build-specific.
  run("mkdir -p %s/www/var" % site_root)
  sudo("ln -s %s/shared/%s_magento_%s_var/log %s/www/var/log" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/session %s/www/var/session" % (www_root, repo, buildtype, site_root))
  sudo("ln -s %s/shared/%s_magento_%s_var/report %s/www/var/report" % (www_root, repo, buildtype, site_root))
  with cd("%s/shared/%s_magento_%s_var" % (www_root, repo, buildtype)):
    sudo("chown -R %s:www-data *" % user)
    sudo("chmod 2775 *")
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
def initial_magento_build(repo, repourl, branch, user, url, www_root, site_root, buildtype, build, config, composer, composer_lock, no_dev, rds, db_name, db_username, mysql_version, db_password, mysql_config, dump_file, magento_password, magento_username, magento_email, magento_firstname, magento_lastname, magento_admin_path, magento_mode, magento_marketplace_username, magento_marketplace_password, cluster):
  # Should we build Magento?
  if magento_marketplace_username and magento_marketplace_password and composer:
    print "===> Provided with Magento repo credentials, let's use them to build Magento"
    # Make sure composer.json exists
    common.PHP.composer_command(site_root, "--no-interaction init")
    # Make sure composer has the credentials we need, global is set to True
    common.PHP.composer_command(site_root, "config http-basic.repo.magento.com %s %s" % (magento_marketplace_username, magento_marketplace_password))
    with cd(site_root):
      # Blow away any existing 'www' directory, we're going to totally recreate the project
      sudo("rm -R www")
      #run("composer create-project --repository-url=https://repo.magento.com/ magento/project-community-edition=2.2.3 www")
      common.PHP.composer_command(site_root, "create-project --repository-url=https://repo.magento.com/ magento/project-community-edition=2.2.3 www", None, no_dev, composer_lock)
      # Commit resulting www directory back to Git
      run("git add -f www")
      run("git commit -m 'Committing the newly built Magento application back to the repository.'")
      # Need to make sure we forward our private key to push
      common.Utils._sshagent_run("cd %s && git push -u origin %s" % (site_root, branch))

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
      print "########### Your Magento site is almost ready!"
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
    # Remove env.php again, because we will *re*set the link in Magento.adjust_files_symlink() momentarily
    sudo("rm app/etc/env.php")

    # Commit resulting config.php file back to Git
    run("git add -f app/etc/config.php")
    run("git commit -m 'Committing config.php back to the repository.'")
    # Note: this happens on app_primary but if we have a cluster this will be shared with other app servers
    # and the later run of Magento/adjust_files_symlink() will ensure all links are in place.
    sudo("mv app/etc/config.php %s/shared/%s_magento_%s_etc/" % (www_root, repo, buildtype))
    sudo("ln -s %s/shared/%s_magento_%s_etc/config.php app/etc/config.php" % (www_root, repo, buildtype))
    # Need to make sure we forward our private key to push
    common.Utils._sshagent_run("cd %s/www && git push -u origin %s" % (site_root, branch))
    # Set perms back to www user
    sudo("chown -R www-data:www-data *")


# Install sample data.
@task
@roles('app_primary')
def initial_build_sample_data(site_root, user, magento_marketplace_username, magento_marketplace_password):
  if magento_marketplace_username and magento_marketplace_password:
    print "===> Installing sample data"
    with cd("%s/www" % site_root):
      # Make sure composer.json exists
      common.PHP.composer_command(site_root + '/www', "--no-interaction init")
      # Set repo.magento.com credentials
      common.PHP.composer_command(site_root + '/www', "config http-basic.repo.magento.com %s %s" % (magento_marketplace_username, magento_marketplace_password))
      # We need Jenkins to own the directories for the installation
      sudo("chown -R %s:%s *" % (user, user))
      # Run the import jobs
      run("php bin/magento sampledata:deploy")
      run("php bin/magento setup:upgrade")
      # Set perms back again to www user
      sudo("chown -R www-data:www-data *")
      print "===> Sample data installed"
  else:
    print "######### We cannot install sample data without repo.magento.com credentials"
    print "===> Please set magento_marketplace_username and magento_marketplace_password in your config.ini file or fabric script executor"


# Copy the dummy vhost and change values.
@task
@roles('app_all')
def initial_build_vhost(webserver, repo, buildtype, url, webserverport):
  # Copy webserver dummy vhosts to server
  print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/vhosts/%s/*' % webserver, '/etc/%s/sites-available' % webserver, mode=0644, use_sudo=True).failed:
    raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
  else:
    print "===> Dummy vhosts copied to app server(s)."

  # Set up the vhost config
  print "===> Setting up an %s vhost" % webserver
  sudo("cp /etc/%s/sites-available/magento-dummy.conf /etc/%s/sites-available/%s.conf" % (webserver, webserver, url))

  # Change other dummy values e.g for logs, ServerName
  sudo("sed -i s/dummyfqdn/%s/g /etc/%s/sites-available/%s.conf" % (url, webserver, url))
  sudo("sed -i s/dummyport/%s/g /etc/%s/sites-available/%s.conf" % (webserverport, webserver, url))
  sudo("sed -i s/dummy/%s.%s/g /etc/%s/sites-available/%s.conf" % (repo, buildtype, webserver, url))

  # Enable the vhost
  sudo("ln -s /etc/%s/sites-available/%s.conf /etc/%s/sites-enabled/%s.conf" % (webserver, url, webserver, url))
  print "Tidy up and remove the dummy vhosts. Don't fail the build if they can't be removed."
  with settings(warn_only=True):
    sudo("rm /etc/%s/sites-available/*dummy*.conf" % webserver)

  url_output = url.lower()
  print "***** Your URL is http://%s *****" % url_output
