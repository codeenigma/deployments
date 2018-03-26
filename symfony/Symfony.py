from fabric.api import *
from fabric.contrib.files import *
import random
import string
import common.ConfigFile
import common.Services
import common.Utils
from common.Utils import *
from common.ConfigFile import *

symfony_version = ''
console_location = ''

@task
@roles('app_primary')
def backup_db(repo, buildtype, build):
  print "===> Ensuring backup directory exists..."
  with settings(warn_only=True):
    if run("mkdir -p ~jenkins/dbbackups").failed:
      raise SystemExit("Could not create directory ~jenkins/dbbackups! Aborting early.")

  print "===> Taking a database backup..."
  # Copy Symfony db backup script to server
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/symfony_backup_db.sh', '/home/jenkins', mode=0755).failed:
    raise SystemExit("Could not copy the Symfony backup script to the application server, aborting because we cannot take a backup")
  else:
    print "===> Remove builds script copied to %s:/home/jenkins/symfony_backup_db.sh" % env.host
  with settings(warn_only=True):
    if sudo("/home/jenkins/symfony_backup_db.sh -d /var/www/live.%s.%s -r %s -b %s -n %s" % (repo, buildtype, repo, buildtype, build)).failed:
      failed_backup = True
    else:
      failed_backup = False

  if failed_backup:
    raise SystemExit("Could not take a database backup prior to launching a new build! Aborting early.")


@task
@roles('app_primary')
def determine_symfony_version(repo, buildtype, build):
  global symfony_version
  global console_location

  print "===> Determining Symfony version..."

  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s/composer.json" % (repo, buildtype, build)).return_code == 0:
      symfony_version = run("grep 'symfony/symfony' /var/www/%s_%s_%s/composer.json | awk '{print $2}' | cut -d '.' -f 1 | cut -d '\"' -f 2" % (repo, buildtype, build))
      print "===> Symfony version is %s" % symfony_version
    else:
      raise SystemExit("Could not find composer.json file. Aborting build.")

  if symfony_version == "2":
    console_location = 'app'
    print "===> Symfony console location is %s/console" % console_location
  else:
    console_location = 'bin'
    print "===> Symfony console location is %s/console" % console_location

  return symfony_version


@task
@roles('app_all')
def update_resources(repo, buildtype, build):
  if symfony_version == "2":
    print "===> Symlinking in cache, log directories"
    with settings(warn_only=True):
      if run("ln -s /var/www/shared/%s_%s_logs /var/www/%s_%s_%s/app/logs" % (repo, buildtype, repo, buildtype, build)).failed:
        raise SystemExit("Could not symlink application logs")
      if run("ln -s /var/www/shared/%s_%s_sessions /var/www/%s_%s_%s/app/sessions" % (repo, buildtype, repo, buildtype, build)).failed:
        raise SystemExit("Could not symlink application sessions")
      if run("mkdir /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not create cache directory")
      if sudo("chown -R www-data:jenkins /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not set cache ownership")
      if sudo("chmod -R g+w /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not set cache permissions")
      print "===> Dealing with data directories - should be /var/www/shared/%s_%s_data" % (repo, buildtype)
      if(exists("/var/www/shared/%s_%s_data" % (repo, buildtype))):
          print "Data directory found! Symlinking in"
          if(not exists("/var/www/%s_%s_%s/data" % (repo, buildtype, build))):
            if sudo ("ln -s /var/www/shared/%s_%s_data /var/www/%s_%s_%s/data" % (repo, buildtype, repo, buildtype, build)).failed:
                print "Could not add a Data symlink, even though we tried"
          else:
            print "Found an existing Data directory in the repo, ignoring"
      print "===> Dealing with uploads directories - should be /var/www/shared/%s_%s_uploads" % (repo, buildtype)
      if(exists("/var/www/shared/%s_%s_uploads" % (repo, buildtype))):
          print "Uploads directory found! Symlinking in"
          if(not exists("/var/www/%s_%s_%s/web/uploads" % (repo, buildtype, build))):
            if sudo ("ln -s /var/www/shared/%s_%s_uploads /var/www/%s_%s_%s/web/uploads" % (repo, buildtype, repo, buildtype, build)).failed:
                print "Could not add an uploads symlink, even though we tried"
          else:
            print "Found an existing uploads directory in the repo, ignoring"
  # Assuming Symfony 3 or higher
  else:
    with settings(warn_only=True):
      print "===> Removing cache, logs and session directories..."
      sudo("rm -r /var/www/%s_%s_%s/var/cache" % (repo, buildtype, build))
      sudo("rm -r /var/www/%s_%s_%s/var/logs" % (repo, buildtype, build))
      sudo("rm -r /var/www/%s_%s_%s/var/sessions" % (repo, buildtype, build))

      if run("mkdir /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not create cache directory")
      if sudo("chown -R www-data:jenkins /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not set cache ownership")
      if sudo("chmod -R g+w /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not set cache permissions")

      print "===> Ensuring permissions are correct on cache, logs and session directories are correct..."
      fix_perms_ownership(repo, buildtype, build)


# Symfony3 or higher only
@task
@roles('app_all')
def symlink_resources(repo, buildtype, build):
  with settings(warn_only=True):
    print "===> Symlinking in cache, logs and sessions directories..."
    if run("ln -s /var/www/%s_%s_%s/app/cache /var/www/%s_%s_%s/var/cache" % (repo, buildtype, build, repo, buildtype, build)).failed:
      print "Could not symlink in cache directory."
      raise SystemExit("Could not symlink in cache directory.")
    if run("ln -s /var/www/shared/%s_%s_logs /var/www/%s_%s_%s/var/logs" % (repo, buildtype, repo, buildtype, build)).failed:
      print "Could not symlink in logs directory."
      raise SystemExit("Could not symlink in logs directory.")
    if run("ln -s /var/www/shared/%s_%s_sessions /var/www/%s_%s_%s/var/sessions" % (repo, buildtype, repo, buildtype, build)).failed:
      print "Could not symlink in sessions directory."
      raise SystemExit("Could not symlink in sessions directory.")
    if run("ln -s /var/www/shared/%s_%s_uploads /var/www/%s_%s_%s/web/uploads" % (repo, buildtype, repo, buildtype, build)).failed:
      print "Could not symlink in uploads directory."
      raise SystemExit("Could not symlink in uploads directory.")


# TODO: This should be a build hook example
@task
@roles('app_all')
def symlink_ckfinder_files(repo, buildtype, build):
  print "===> Symlinking in ckfinder files directory, /var/www/shared/%s_%s_userfiles, to web/userfiles" % (repo, buildtype)
  sudo("ln -s /var/www/shared/%s_%s_userfiles /var/www/%s_%s_%s/web/userfiles" % (repo, buildtype, repo, buildtype, build))

# TODO: This should be a build hook example
@task
@roles('app_all')
def ckfinder_install(repo, buildtype, build, console_buildtype):
  print "===> Installing ckfinder"
  if run("cd /var/www/%s_%s_%s; php %s/console --env=%s ckfinder:download" % (repo, buildtype, build, console_location, console_buildtype)).failed:
    raise SystemExit("Could not download CKFinder! Aborting!")
  if run("cd /var/www/%s_%s_%s; php %s/console --env=%s assets:install" % (repo, buildtype, build, console_location, console_buildtype)).failed:
    raise SystemExit("Could not install CKFinder! Aborting!")


@task
@roles('app_all')
def set_symfony_env(repo, buildtype, build, console_buildtype):
  print "===> Setting symfony environment..."

  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s/web/app_%s.php" % (repo, buildtype, build, console_buildtype)).return_code == 0:
      print "Moving app_%s.php to app.php." % console_buildtype
      sudo("rm /var/www/%s_%s_%s/web/app.php" % (repo, buildtype, build))
      sudo("mv /var/www/%s_%s_%s/web/app_%s.php /var/www/%s_%s_%s/web/app.php" % (repo, buildtype, build, console_buildtype, repo, buildtype, build))

    else:
      print "Could not find an app.php file for this environment, checking there's a default app.php."
      if run("stat /var/www/%s_%s_%s/web/app.php" % (repo, buildtype, build)).failed:
        raise SystemExit("We don't appear to have any valid app.php files. Aborting!")


@task
@roles('app_primary')
def run_migrations(repo, buildtype, build, console_buildtype):
  with settings(warn_only=True):
    print "===> Check if there are any pending migrations..."
    if run("cd /var/www/%s_%s_%s; php %s/console --env=%s doctrine:migrations:status" % (repo, buildtype, build, console_location, console_buildtype)).failed:
      print "Could not check migration status. Aborting."
      raise SystemExit("Could not check migration status. Aborting.")
    else:
      migrations = run("cd /var/www/%s_%s_%s; php %s/console --env=%s doctrine:migrations:status | grep \"New Migrations\" | awk '{print $4}'" % (repo, buildtype, build, console_location, console_buildtype))
      print "DEBUG: migrations = %s" % migrations
      if migrations == "0":
        print "No migrations to run. Proceeding on..."
      else:
        print "===> Running migrations..."
        if run("cd /var/www/%s_%s_%s; php %s/console --env=%s doctrine:migrations:migrate --quiet" % (repo, buildtype, build, console_location, console_buildtype)).failed:
          print "Could not run migrations. Aborting."
          raise SystemExit("Could not run migrations. Aborting.")


@task
@roles('app_all')
def clear_cache(repo, buildtype, build, console_buildtype):
  print "===> Clearing cache on %s environment..." % buildtype
  with settings(warn_only=True):
    with cd("/var/www/%s_%s_%s" % (repo, buildtype, build)):
      if run("php %s/console --env=%s cache:clear" % (console_location, console_buildtype)).failed:
        print "Could not clear cache. Abort, just to be safe."
        raise SystemExit("Could not clear cache. Abort, just to be safe.")
      else:
        print "%s cache cleared! Fixing up perms and ownership..." % console_buildtype
        fix_perms_ownership(repo, buildtype, build)


@task
@roles('app_all')
def fix_perms_ownership(repo, buildtype, build):
  with settings(warn_only=True):
    if sudo("chown -R www-data:jenkins /var/www/%s_%s_%s/app/cache" % (repo, buildtype, build)).failed:
      print "Could not set cache ownership."
      raise SystemExit("Could not set cache ownership.")
    else:
      sudo("find /var/www/%s_%s_%s/app/cache -type d -print0 | xargs -r -0 chmod 775" % (repo, buildtype, build))
      sudo("find /var/www/%s_%s_%s/app/cache -type f -print0 | xargs -r -0 chmod 664" % (repo, buildtype, build))
    if sudo("chown -R www-data:jenkins /var/www/shared/%s_%s_logs" % (repo, buildtype)).failed:
      print "Could not set logs ownership."
      raise SystemExit("Could not set logs ownership.")
    else:
      sudo("find /var/www/shared/%s_%s_logs -type d -print0 | xargs -r -0 chmod 775" % (repo, buildtype))
      sudo("find /var/www/shared/%s_%s_logs -type f -print0 | xargs -r -0 chmod 664" % (repo, buildtype))
    if sudo("chown -R www-data:jenkins /var/www/shared/%s_%s_sessions" % (repo, buildtype)).failed:
      print "Could not set sessions ownership."
      raise SystemExit("Could not set session ownership.")
    else:
      sudo("find /var/www/shared/%s_%s_sessions -type d -print0 | xargs -r -0 chmod 770" % (repo, buildtype))
      sudo("find /var/www/shared/%s_%s_sessions -type f -print0 | xargs -r -0 chmod 660" % (repo, buildtype))
    if sudo("chown -R www-data:jenkins /var/www/shared/%s_%s_uploads" % (repo, buildtype)).failed:
      print "Could not set uploads ownership."
      raise SystemExit("Could not set uploads ownership.")
    else:
      sudo("find /var/www/shared/%s_%s_uploads -type d -print0 | xargs -r -0 chmod 775" % (repo, buildtype))
      sudo("find /var/www/shared/%s_%s_uploads -type f -print0 | xargs -r -0 chmod 664" % (repo, buildtype))
