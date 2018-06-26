from fabric.api import *
from fabric.contrib.files import *
import Revert


# Adjust settings.php. Copy the relevant file based on the branch, delete the rest.
@task
@roles('app_all')
def adjust_settings_php(repo, branch, build, buildtype, alias, site):

  # In some cases it seems jenkins loses write permissions to the site directory
  # Let's make sure!
  sudo("chmod -R 775 /var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site))

  # Check there is a settings.inc file, there are no cases where there should not be!
  if run("stat /var/www/config/%s_%s.settings.inc" % (alias, branch)):
    with settings(warn_only=True):
      if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, site)).succeeded:
        run("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/%s_%s_%s/www/sites/%s/unused.settings.php" % (repo, branch, build, site, repo, branch, build, site))

    if run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, site)).failed:
      raise SystemExit("######## Couldn't symlink in settings.inc file! Aborting build.")
  else:
    raise SystemExit("######## Couldn't find any settings.inc! This site probably failed its initial build and needs fixing. Aborting early! TIP: Add a /var/www/config/%s_%s.settings.inc file manually and do a file_exists() check for /var/www/%s_%s_%s/www/sites/%s/%s.settings.php and if it exists, include it. Then symlink that to /var/www/%s_%s_%s/www/sites/%s/settings.php." % (alias, branch, repo, branch, build, site, buildtype, repo, branch, build, site))

  with settings(warn_only=True):
    # Let's make sure we're checking for $buildtype.settings.php.
    # If so, we'll update the build number - if not, we'll add the check to the bottom of the file.
    settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
    if run('grep "\$file = \'\/var\/www\/%s" %s' % (repo, settings_file)).return_code == 0:
      print "===> %s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
      replace_string = "/var/www/.+_.+_build_[0-9]+/.+\.settings\.php"
      replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
      sed(settings_file, replace_string, replace_with, limit='', use_sudo=False, backup='.bak', flags="i", shell=False)
    else:
      append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include($file);
}""" % (repo, branch, build, site, buildtype)
      append(settings_file, append_string, use_sudo=True)
      print "===> %s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file


# Adjust shared files symlink
@task
@roles('app_all')
def adjust_files_symlink(repo, branch, build, alias, site):
  print "===> Setting the symlink for files"
  sudo("ln -s /var/www/shared/%s_%s_files/ /var/www/%s_%s_%s/www/sites/%s/files" % (alias, branch, repo, branch, build, site))


# If we have a drushrc.php file in the site that reflects this branch, copy that into place
@task
@roles('app_all')
def adjust_drushrc_php(repo, branch, build, site):
  with settings(warn_only=True):
    print "===> Copying %s.drushrc.php to drushrc.php if it exists" % branch
    if run("stat /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php" % (repo, branch, build, site, branch)).failed:
      print "===> Couldn't find /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php, so moving on..." % (repo, branch, build, site, branch)
    else:
      if sudo("cp /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php /var/www/%s_%s_%s/www/sites/%s/drushrc.php" % (repo, branch, build, site, branch, repo, branch, build, site)).failed:
        print "####### Could not copy /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php to /var/www/%s_%s_%s/www/sites/%s/drushrc.php. Continuing with build, but perhaps have a look into why the file couldn't be copied." % (repo, branch, build, site, branch, repo, branch, build, site)
      else:
        print "===> Copied /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php to /var/www/%s_%s_%s/www/sites/%s/drushrc.php" % (repo, branch, build, site, branch, repo, branch, build, site)
