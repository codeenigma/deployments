from fabric.api import *
from fabric.contrib.files import sed
import random
import string
# Custom Code Enigma modules
import common.Utils
import common.MySQL
# Needed to get variables set in modules back into the main script
from common.Utils import *

# Stuff to do when this is the initial build
@task
def initial_build(repo, url, branch, build, buildtype, profile, webserver, webserverport, config, db_name, db_username, db_password, mysql_version, mysql_config, install_type, cluster=False, autoscale=False, rds=False):
  print "===> This looks like the first build! We have some things to do.."

  print "===> Setting the live document root symlink"
  sudo("ln -s /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))

  print "===> Making the shared files dir and setting symlink"
  sudo("mkdir -p /var/www/shared/%s_%s_uploads" % (repo, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s_uploads" % (repo, branch))
  sudo("ln -s /var/www/shared/%s_%s_uploads /var/www/%s_%s_%s/www/wp-content/uploads" % (repo, branch, repo, branch, build))

  print "===> Preparing the database"
  # this process creates a database, database user/pass, imports the db dump from the repo
  # and generates the wp-config.php database file.

  # We can default these to None, mysql_new_database() will sort itself out
  list_of_app_servers = None
  db_host = None
  # For clusters we need to do some extra things
  if cluster or autoscale:
    # This is the Database host that we need to insert into wordpress config. It is different from the main db host because it might be a floating IP
    db_host = config.get('WPDBHost', 'dbhost')
    print "db is %s" % (db_host)
    # Convert a list of apps back into a string, to pass to the MySQL new database function for setting appropriate GRANTs to the database
    list_of_app_servers = env.roledefs['app_all']
    print "app list is %s" % (list_of_app_servers)
  if cluster and config.has_section('AppIPs'):
    list_of_app_servers = env.roledefs['app_ip_all']

  # Prepare the database
  # We'll get back db_name, db_username, db_password and db_host from this call as a list in new_database
  new_database = common.MySQL.mysql_new_database(repo, buildtype, rds, db_name, db_host, db_username, mysql_version, db_password, mysql_config, list_of_app_servers)

  print "===> Waiting 10 seconds to let MySQL internals catch up"
  time.sleep(10)

  # Copy wp-config.php into place
  with settings(warn_only=True):
    if run("stat /var/www/live.%s.%s/wp-config.php.%s" % (repo, branch, branch)).return_code == 0:
      sudo("cp /var/www/live.%s.%s/wp-config.php.%s /var/www/live.%s.%s/wp-config.php" % (repo, branch, branch, repo, branch))
    else:
      print "No wp-config.php.%s file, continuing..." % branch


  # wp-cli site install.
  if install_type == "www":
    install_path = "/var/www/live.%s.%s/www" % (repo, branch)
  else:
    install_path = "/var/www/live.%s.%s" % (repo, branch)
  sudo("wp --path=%s --allow-root core config --dbname=%s --dbuser=%s --dbpass=%s --dbhost=%s" % (install_path, new_database[0], new_database[1], new_database[2], new_database[3]))
  sudo("wp --path=%s --allow-root core install --url=%s --title=%s --admin_user=codeenigma --admin_email=sysadm@codeenigma.com --admin_password=%s" % (install_path, url, new_database[0], new_database[2]))

  print "===> Setting up an %s vhost" % webserver
  # Copy vhost to server(s)
  print "===> Placing new copies of dummy vhosts for %s before proceeding" % webserver
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/vhosts/%s/wp-*' % webserver, '/etc/%s/sites-available' % webserver, mode=0755, use_sudo=True).failed:
    raise SystemExit("===> Couldn't copy over our dummy vhosts! Aborting.")
  else:
    print "===> Dummy vhosts copied to app server(s)."
  # Abort if the vhost already exists - something strange has happened here,
  # perhaps we shouldn't have been doing a fresh install at all
  with settings(warn_only=True):
    if run("stat /etc/%s/sites-available/%s.conf" % (webserver, url)).return_code == 0:
      raise SystemError("The VirtualHost config file /etc/%s/sites-available/%s.conf already existed! Aborting." % (webserver, url))

  # Set up vhost here
  sudo("cp /etc/%s/sites-available/wp-dummy.conf /etc/%s/sites-available/%s.conf" % (webserver, webserver, url))

  sudo("sed -i s/dummyfqdn/%s/g /etc/%s/sites-available/%s.conf" % (url, webserver, url))
  sudo("sed -i s/dummyport/%s/g /etc/%s/sites-available/%s.conf" % (webserverport, webserver, url))
  sudo("sed -i s/dummy/%s.%s/g /etc/%s/sites-available/%s.conf" % (repo, branch, webserver, url))
  sudo("ln -s /etc/%s/sites-available/%s.conf /etc/%s/sites-enabled/%s.conf" % (webserver, url, webserver, url))
  print "***** Your URL is http://%s *****" % url

  print "===> Moving wp-config.php to shared area /var/www/shared/%s_%s.wp-config.inc. Do an 'include' of this in your main wp-config.php, or else it will be symlinked directly as wp-config.php" % (repo, branch)
  sudo("mv /var/www/live.%s.%s/www/wp-config.php /var/www/shared/%s_%s.wp-config.inc; ln -s /var/www/shared/%s_%s.wp-config.inc /var/www/live.%s.%s/www/wp-config.php" % (repo, branch, repo, branch, repo, branch, repo, branch))
  sudo("chown jenkins:www-data /var/www/shared/%s_%s.wp-config.inc" % (repo, branch))
  sudo("chmod 644 /var/www/shared/%s_%s.wp-config.inc" % (repo, branch))

# Greg: Wordpress has a kind of inbuilt poor man's cron, so leaving this so we don't forget
# but ignoring porting it for now.
#
# Generate a crontab for running drush cron on this site
#def generate_drush_cron(repo, branch):
#  print "===> Generating Drush cron for this site if it isn't there already"
#  sudo("/usr/local/bin/drush_cron %s %s" % (repo, branch))
