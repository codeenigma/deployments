from fabric.api import *
from fabric.contrib.files import *
import Revert


# Adjust settings.php. Copy the relevant file based on the branch, delete the rest.
@task
@roles('app_all')
def adjust_settings_php(repo, branch, build, buildtype, alias, site):

  # We do not want settings.inc on NAS in case it fails
  # This can be removed at some later date because initial_build() takes care of it going forwards
  # For now this is just to catch "first build" scenarios where a config directory is required but missing
  with settings(warn_only=True):
    if run("stat /var/www/config").failed:
      # No "config" directory
      sudo("mkdir --mode 0755 /var/www/config")
      sudo("chown jenkins:www-data /var/www/config")
      
  # In some cases it seems jenkins loses write permissions to the site directory
  # Let's make sure!
  sudo("chmod -R 775 /var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site))

  # Process for adjusting settings.php is this:
  # 1. Check if a repo_branch.settings.inc file exists in /var/www/config
  # 2. If it doesn't, check if a settings.php exists for this site.
  # 3. If that doesn't, check if $buildtype.settings.php exists for this site, as a last resort.
  # 4. If $buildtype.settings.php doesn't exist, raise a SystemExit and get out.
  # 5. If $buildtype.settings.php DOES exist, add a commented line to the bottom of it to say it copied to settings.inc and to not include $buildtype.settings.php in it, otherwise there'd be duplicate config values.
  # 6. If settings.php exists, see if it contains the file_exists() check, and if it doesn't, append that check to the bottom of settings.php.
  # 7. If a settings.inc file was found:
  # 8. Check if it contains the comment from #5 and if it does, do NOT append file_exists() check to bottom of file.
  # 9. If comment from #5 is not found, append file_exists() check to bottom of file
  # 10. If there's no settings.php, symlink in settings.inc file.

  with settings(warn_only=True):
    # 1. First check if the settings.inc file exists in 'config'
    if run("stat /var/www/config/%s_%s.settings.inc" % (alias, branch)).failed:
      # 2. We didn't find the shared file. Check if settings.php exists for this site.
      print "The shared settings file /var/www/config/%s_%s.settings.inc was not found. We'll try and move a sites/%s/settings.php file there, if it exists." % (alias, branch, repo, branch, site)
      if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, site)).failed:
        # 3. Doesn't look like settings.php exists for this site. We'll see if a $branch.settings.php file exists instead, as a last resort.
        print "We couldn't find /var/www/%s_%s_%s/www/sites/%s/settings.php, so we'll search for a buildtype specific file as a last resort." % (repo, branch, build, site)
        if run("stat /var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)).failed:
          # 4. We couldn't find a $buildtype.settings.php file either. This isn't right, so let's raise an error and get out of here.
          raise SystemExit("Couldn't find any settings.php whatsoever! As it's unlikely we'll be able to bootstrap a site, we're going to abort early. TIP: Add a /var/www/config/%s_%s.settings.inc file manually and do a file_exists() check for /var/www/%s_%s_%s/www/sites/%s/%s.settings.php and if it exists, include it. Then symlink that to /var/www/%s_%s_%s/www/sites/%s/settings.php." % (alias, branch, repo, branch, build, site, buildtype, repo, branch, build, site))
        else:
          # 5. We DID find $buildtype.settings.php
          print "We found /var/www/%s_%s_%s/www/sites/%s/%s.settings.php, so we'll add a commented line at the bottom of it to indicate it's copied to /var/www/config/%s_%s.settings.inc. This will prevent %s.settings.php being included in the settings.inc file in subsequent builds. We'll also move it to /var/www/config/%s_%s.settings.inc." % (repo, branch, build, site, buildtype, alias, branch, buildtype, alias, branch)
          settings_file = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
          append(settings_file, '# Copied from branch settings')
          sudo("mv /var/www/%s_%s_%s/www/sites/%s/%s.settings.php /var/www/config/%s_%s.settings.inc" % (repo, branch, build, site, buildtype, alias, branch))
          sudo("chown jenkins:www-data /var/www/config/%s_%s.settings.inc" % (alias, branch))
          sudo("chmod 664 /var/www/config/%s_%s.settings.inc" % (alias, branch))
          run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, site))
      else:
        # 6. We found settings.php. Let's see if it's checking for $buildtype.settings.php. If it's not, we'll add the check to the bottom of the file.
        contain_string = "if (file_exists($file)) {"
        settings_file = "/var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, site)
        does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
        if not does_contain:
          append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
include_once($file);
}""" % (repo, branch, build, site, buildtype)
          append(settings_file, append_string, use_sudo=True)
          print "%s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file
        else:
          #print "%s already has a file_exists() check, so it wasn't appened to the bottom of the settings.inc file." % settings_file
          print "%s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
          replace_string = "/var/www/.+_.+_build_[0-9]+/.+\.settings\.php"
          replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
          sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='.bak', flags="i", shell=False)
    else:
      # 7. We found a settings.inc file in /var/www/config. Let's see if we first should append anything to it, and then if we need to.
      contain_string = '# Copied from branch settings'
      settings_file = "/var/www/config/%s_%s.settings.inc" % (alias, branch)
      does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
      if does_contain:
        # 8. The settings.inc contains the comment from #5. Therefore, we won't add a file_exists($buildtype.settings.php) check.
        print "%s contains '%s', so we won't append a file_exists() check and include_once. This is because the settings.php file was copied from sites/%s/%s.settings.php and it wouldn't make sense to include itself." % (settings_file, contain_string, site, buildtype)
      else:
        # 9. The settings.inc does not contain a comment (from #5), so we'll see if we need to append a file_exists() check.
        print "%s does not contain '%s', so we'll check if we need to append a file_exists() check to settings.inc." % (settings_file, contain_string)
        contain_string = "if (file_exists($file)) {"
        does_contain = contains(settings_file, contain_string, exact=True, use_sudo=True)
        if not does_contain:
          append_string = """$file = '/var/www/%s_%s_%s/www/sites/%s/%s.settings.php';
if (file_exists($file)) {
  include_once($file);
}""" % (repo, branch, build, site, buildtype)
          append(settings_file, append_string, use_sudo=True)
          print "%s did not have a file_exists() check, so it was appended to the bottom of the file." % settings_file
        else:
          #print "%s already has a file_exists() check, so it wasn't appened to the bottom of the settings.inc file." % settings_file
          print "%s already has a file_exists() check. We need to replace the build number so the newer %s.settings.php file is used." % (settings_file, buildtype)
          replace_string = "/var/www/.+_.+_build_[0-9]+/.+\.settings\.php"
          replace_with = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
          sed(settings_file, replace_string, replace_with, limit='', use_sudo=True, backup='.bak', flags="i", shell=False)
      # 10. Let's see if there's a settings.php file in the site directory. If not, we'll symlink in our settings.inc.
      if run("stat /var/www/%s_%s_%s/www/sites/%s/settings.php" % (repo, branch, build, site)).failed:
        print "There's a settings.inc file, but no main settings.php file. We'll symlink in our settings.inc file."
        run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, site))
      else:
        print "We found a settings.inc file AND a main settings.php file. We'll move settings.php to settings.php.bak and symlink in the settings.inc file."
        sudo("mv /var/www/%s_%s_%s/www/sites/%s/settings.php /var/www/%s_%s_%s/www/sites/%s/settings.php.bak" % (repo, branch, build, site, repo, branch, build, site))
        run("ln -s /var/www/config/%s_%s.settings.inc /var/www/%s_%s_%s/www/sites/%s/settings.php" % (alias, branch, repo, branch, build, site))


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
      print "Couldn't find /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php, so moving on..." % (repo, branch, build, site, branch)
    else:
      if sudo("cp /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php /var/www/%s_%s_%s/www/sites/%s/drushrc.php" % (repo, branch, build, site, branch, repo, branch, build, site)).failed:
        print "Could not copy /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php to /var/www/%s_%s_%s/www/sites/%s/drushrc.php. Continuing with build, but perhaps have a look into why the file couldn't be copied." % (repo, branch, build, site, branch, repo, branch, build, site)
      else:
        print "Copied /var/www/%s_%s_%s/www/sites/%s/%s.drushrc.php to /var/www/%s_%s_%s/www/sites/%s/drushrc.php" % (repo, branch, build, site, branch, repo, branch, build, site)

