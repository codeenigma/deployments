from fabric.api import *
from fabric.contrib.files import sed
import random
import string
# Custom Code Enigma modules
import common.Utils
# Needed to get variables set in modules back into the main script
from common.Utils import *

# Stuff to do when this is the initial build
@task
def initial_build(repo, url, branch, build, profile, webserverport):
  print "===> This looks like the first build! We have some things to do.."

  print "===> Setting the live document root symlink"
  sudo("ln -s /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))

  print "===> Making the shared files dir and setting symlink"
  sudo("mkdir -p /var/www/shared/%s_%s_uploads" % (repo, branch))
  sudo("chown www-data:staff /var/www/shared/%s_%s_uploads" % (repo, branch))
  sudo("ln -s /var/www/shared/%s_%s_uploads /var/www/%s_%s_%s/www/wp-content/uploads" % (repo, branch, repo, branch, build))

  print "===> Preparing the database"
  # this process creates a database, database user/pass, imports the db dump from the repo
  # and generates the wp-config.php database file.
  newpass = common.Utils._gen_passwd()

  # Check if a db/ directory exists first.
  db_dir = False
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s -maxdepth 1 -type d -name db | egrep '.*'" % (repo, branch, build)).return_code == 0:
      db_dir = True

  if db_dir:
    sudo("bunzip2 /var/www/%s_%s_%s/db/*.sql.bz2" % (repo, branch, build))
    # Copying the database script to the server.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    if put(script_dir + '/../util/mysqlprepare_wp.sh', '/home/jenkins', mode=0755).failed:
      raise SystemExit("Could not copy the database script to the application server, aborting because we won't be able to make a database")
    else:
      print "===> Database preparation script mysqlprepare_wp.sh copied to %s:/home/jenkins/mysqlprepare_wp.sh" % (env.host)
    # Note, Wordpress version of script, mysqlprepare_wp.sh <databasename> <databasepass> <site_root> <branch> <dumpfile>
    sudo("/home/jenkins/mysqlprepare_wp.sh %s %s /var/www/live.%s.%s %s $(find /var/www/%s_%s_%s/db -type f -name *.sql)" % (repo, newpass, repo, branch, branch, repo, branch, build))
  else:
    sitedir = "/var/www/%s_%s_%s/www" % (repo, branch, build)
    # Copying the database script to the server.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    if put(script_dir + '/../util/mysqlpreparenoimport_wp.sh', '/home/jenkins', mode=0755).failed:
      raise SystemExit("Could not copy the database script to the application server, aborting because we won't be able to make a database")
    else:
      print "===> Database preparation script mysqlpreparenoimport_wp.sh copied to %s:/home/jenkins/mysqlpreparenoimport_wp.sh" % (env.host)
    sudo("/home/jenkins/mysqlpreparenoimport_wp.sh %s %s %s %s %s %s" % (repo, newpass, sitedir, branch, profile, url))

  webserver = "nginx"

  print "===> Setting up an %s vhost" % webserver
  # Copy Nginx vhost to server(s)
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

# Greg: This is all Drupal specific, so for the moment commenting for a simple build.
  # If this is dev/staging, we want to sanitise the database ASAP.
#  dev_stage_servers = ['dev1.codeenigma.com', 'dev2.codeenigma.com', 'dev3.codeenigma.com', 'stage1.codeenigma.com', 'stage2.codeenigma.com', 'stage3.codeenigma.com']
#  dev_stage_server = [server for server in dev_stage_servers if env.host in server]

#  if dev_stage_server:
#    print "===> Sanitising database"
#    with cd("/var/www/live.%s.%s/www/sites/default" % (repo, branch)):
#      run("drush sql-query \"UPDATE users SET mail = CONCAT(name, '@example.com')\"")
#      run("drush sql-query \"UPDATE users SET mail = 'support@codeenigma.com' WHERE uid = 1\"")
#      run("drush user-password `drush uinf 1 | grep name | cut -d\: -f2` --password=admin")

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
