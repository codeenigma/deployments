from fabric.api import *
from fabric.contrib.files import *
import Revert
from string import replace


# Adjust settings.php. Copy the relevant file based on the branch, delete the rest.
# Failures here should be reverting the build entirely. If it fails to find settings.inc, or symlink in the file, the build will fail and the site being deployed and all sites that have been deployed will remain offline. All sites that have been deployed should have their databases reverted, as they could have had database updates applied.
@task
@roles('app_all')
def adjust_settings_php(repo, branch, build, buildtype, alias, site, www_root, application_directory):

  # In some cases it seems jenkins loses write permissions to the site directory
  # Let's make sure!
  sudo("chmod -R 775 %s/%s_%s_%s/%s/sites/%s" % (www_root, repo, branch, build, application_directory, site))

  # Check there is a settings.inc file, there are no cases where there should not be!
  if run("stat %s/config/%s_%s.settings.inc" % (www_root, alias, branch)):
    with settings(warn_only=True):
      if run("stat %s/%s_%s_%s/%s/sites/%s/settings.php" % (www_root, repo, branch, build, application_directory, site)).succeeded:
        run("mv %s/%s_%s_%s/%s/sites/%s/settings.php %s/%s_%s_%s/%s/sites/%s/unused.settings.php" % (www_root, repo, branch, build, application_directory, site, www_root, repo, branch, build, application_directory, site))

    if run("ln -s %s/config/%s_%s.settings.inc %s/%s_%s_%s/%s/sites/%s/settings.php" % (www_root, alias, branch, www_root, repo, branch, build, application_directory, site)).failed:
      raise SystemExit("######## Couldn't symlink in settings.inc file! Aborting build.")
  else:
    raise SystemExit("######## Couldn't find any settings.inc! This site probably failed its initial build and needs fixing. Aborting early! TIP: Add a %s/config/%s_%s.settings.inc file manually and do a file_exists() check for %s/%s_%s_%s/%s/sites/%s/%s.settings.php and if it exists, include it. Then symlink that to %s/%s_%s_%s/%s/sites/%s/settings.php." % (www_root, alias, branch, www_root, repo, branch, build, application_directory, site, buildtype, www_root, repo, branch, build, application_directory, site))

  with settings(warn_only=True):
    # Let's make sure we're checking for $buildtype.settings.php.
    # If so, we'll update the build number - if not, we'll add the check to the bottom of the file.
    settings_file = "%s/config/%s_%s.settings.inc" % (www_root, alias, branch)
    grep_www_root = www_root.replace("/", "\/")
    if run('grep "\$file = \'%s\/%s" %s' % (grep_www_root, repo, settings_file)).return_code == 0:
      print "===> %s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
      sudo('sed -i.bak "s:%s/.\+_.\+_build_[0-9]\+/.\+/.\+\.settings\.php:%s/%s_%s_%s/%s/sites/%s/%s.settings.php:g" %s' % (www_root, www_root, repo, branch, build, application_directory, site, buildtype, settings_file))
    else:
      append_string = """$file = '%s/%s_%s_%s/%s/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include($file);
}""" % (www_root, repo, branch, build, application_directory, site, buildtype)
      append(settings_file, append_string, use_sudo=True)
      print "===> %s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file


# Adjust shared files symlink
@task
@roles('app_all')
def adjust_files_symlink(repo, branch, build, alias, site, www_root, application_directory):
  print "===> Setting the symlink for files"
  sudo("ln -s %s/shared/%s_%s_files/ %s/%s_%s_%s/%s/sites/%s/files" % (www_root, alias, branch, www_root, repo, branch, build, application_directory, site))


# If we have a drushrc.php file in the site that reflects this branch, copy that into place
@task
@roles('app_all')
def adjust_drushrc_php(repo, branch, build, site, www_root, application_directory):
  with settings(warn_only=True):
    print "===> Copying %s.drushrc.php to drushrc.php if it exists" % branch
    if run("stat %s/%s_%s_%s/%s/sites/%s/%s.drushrc.php" % (www_root, repo, branch, build, site, application_directory, branch)).failed:
      print "===> Couldn't find %s/%s_%s_%s/%s/sites/%s/%s.drushrc.php, so moving on..." % (www_root, repo, branch, build, site, application_directory, branch)
    else:
      if sudo("cp %s/%s_%s_%s/%s/sites/%s/%s.drushrc.php %s/%s_%s_%s/%s/sites/%s/drushrc.php" % (www_root, repo, branch, build, application_directory, site, branch, www_root, repo, branch, build, application_directory, site)).failed:
        print "####### Could not copy %s/%s_%s_%s/%s/sites/%s/%s.drushrc.php to %s/%s_%s_%s/%s/sites/%s/drushrc.php. Continuing with build, but perhaps have a look into why the file couldn't be copied." % (www_root, repo, branch, build, application_directory, site, branch, www_root, repo, branch, build, application_directory, site)
      else:
        print "===> Copied %s/%s_%s_%s/%s/sites/%s/%s.drushrc.php to %s/%s_%s_%s/%s/sites/%s/drushrc.php" % (www_root, repo, branch, build, site, application_directory, branch, www_root, repo, branch, build, application_directory, site)
