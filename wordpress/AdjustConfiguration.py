from fabric.api import *
from fabric.contrib.files import *

# Adjust wp-config.php. Copy the relevant file based on the branch, delete the rest.
@task
def adjust_wp_config(repo, branch, build):
  # The logic here is a bit complex due to accounting for our legacy ways.
  # The structure is this:
  # 1. Check if a 'shared' wp-config.inc file exists in /var/www/shared yet
  # 2. If it doesn't, check if a wp-config.php.$branch file exists. This is our legacy style.
  # 3. If the wp-config.php.$branch existed, move it to /var/www/shared, effectively making it the 'shared' wp-config.inc file. Symlink this so that it maps to 'wp-config.php' for now, as there was nothing else
  # 4. If the wp-config.php.$branch didn't exist, see if a wp-config.php file existed (for some reason! New client?)
  # 5. If the wp-config.php existed, move it to /var/www/shared, effectively making it the 'shared' wp-config.inc file. Symlink this so that it maps to 'wp-config.php' for now, as there was nothing else
  # 6. If neither a wp-config.inc, wp-config.php.$branch NOR wp-config.php existed, let's just abort. There's no settings whatsoever, what is going on?
  # 7. Leave tips in all of the above, that wp-config.php _should_ be added to git but with a simple 'include' that includes the shared wp-config.inc, which is where database credentials etc should remain
  # 8. If a shared wp-config.inc file already existed, that's good news. If no wp-config.php exists in the repo, symlink the .inc file to map to wp-config.php and leave a note as above, that someone should create it
  # 9. If a shared wp-config.inc file already existed, and there was a wp-config.php in the repo already, we are fully 'upgraded' to the new model. Do nothing at all. We presume that the repo's wp-config.php does an 'include' or whatever, of the shared wp-config.inc to fetch creds.

  # 1. First, check if the 'shared' file exists
  with settings(warn_only=True):
    if run("stat /var/www/config/%s_%s.wp-config.inc" % (repo, branch)).failed:
      # 2. Didn't find such a file, see if we are on a legacy system with a wp-config.php.$branch and move it to shared area"
      print "The shared settings file /var/www/config/%s_%s.wp-config.inc was not found. We'll try and move your branch-specific wp-config.php there if it exists" % (repo, branch)
      if run("stat /var/www/%s_%s_%s/www/wp-config.php.%s" % (repo, branch, build, branch)).failed:
        # 4. didn't find such a wp-config.php.$branch file. Try looking for generic wp-config.php
        print "We couldn't find a branch-specific wp-config.php file in /var/www/%s_%s_%s/www/wp-config.php.%s! We'll try one more time with a generic wp-config.php" % (repo, branch, build, branch)
        if run("stat /var/www/%s_%s_%s/www/wp-config.php" % (repo, branch, build)).failed:
          # 6. Didn't find even a wp-config.php file! No settings! Let's get out of here
          raise SystemExit("Could not find any wp-config.php whatsoever! It's unlikely we can bootstrap such a site. Aborting early. Tip: Add /var/www/config/%s_%s.wp-config.inc containing DB credentials, and make a simple /var/www/%s_%s_%s/www/wp-config.php that does an 'include' of this file." % (repo, branch, repo, branch, build))
        else:
          # 5. copy wp-config.php file to shared area and symlink it, leaving a tip to make a simple include file
          sudo("mv /var/www/%s_%s_%s/www/wp-config.php /var/www/config/%s_%s.wp-config.inc" % (repo, branch, build, repo, branch))
          sudo("chown jenkins:www-data /var/www/config/%s_%s.wp-config.inc" % (repo, branch))
          sudo("chmod 644 /var/www/config/%s_%s.wp-config.inc" % (repo, branch))
          run("ln -s /var/www/config/%s_%s.wp-config.inc /var/www/%s_%s_%s/www/wp-config.php" % (repo, branch, repo, branch, build))
          print "Tip: modify your /var/www/%s_%s_%s/www/wp-config.php so that it does a PHP include of /var/www/config/%s_%s.wp-config.inc, as that's where credentials are" % (repo, branch, build, repo, branch)

      # 3. We found a wp-config.php.$branch file - move it to shared area and symlink it, leaving a tip to make a simple include file
      else:
        print "Moving /var/www/%s_%s_%s/www/wp-config.php.%s to /var/www/config/%s_%s.wp-config.inc" % (repo, branch, build, branch, repo, branch)
        sudo("mv /var/www/%s_%s_%s/www/wp-config.php.%s /var/www/config/%s_%s.wp-config.inc" % (repo, branch, build, branch, repo, branch))
        sudo("chown jenkins:www-data /var/www/config/%s_%s.wp-config.inc" % (repo, branch))
        sudo("chmod 644 /var/www/config/%s_%s.wp-config.inc" % (repo, branch))
        run("ln -s /var/www/config/%s_%s.wp-config.inc /var/www/%s_%s_%s/www/wp-config.php" % (repo, branch, repo, branch, build))
        print "Tip: make a simple /var/www/%s_%s_%s/www/wp-config.php that does a PHP include of /var/www/config/%s_%s.wp-config.inc, as that's where credentials are" % (repo, branch, build, repo, branch)
    # Else, we found a wp-config.inc in the shared area.
    else:
      print "We found the /var/www/config/%s_%s.wp-config.inc file, we'll symlink it if you have no wp-config.php file in the site root, or else do nothing" % (repo, branch)
      if run("stat /var/www/%s_%s_%s/www/wp-config.php" % (repo, branch, build)).failed:
        # 8. We found a wp-config.inc shared file, but no main wp-config.php, so let's symlink the shared one to be wp-config.php
        run("ln -s /var/www/config/%s_%s.wp-config.inc /var/www/%s_%s_%s/www/wp-config.php" % (repo, branch, repo, branch, build))
        print "Tip: make a simple /var/www/%s_%s_%s/www/wp-config.php that does a PHP include of /var/www/config/%s_%s.wp-config.inc, as that's where credentials are" % (repo, branch, build, repo, branch) 


# Adjust shared files symlink
@task
def adjust_files_symlink(repo, branch, build):
  print "===> Setting the symlink for files"
  sudo("ln -s /var/www/shared/%s_%s_uploads/ /var/www/%s_%s_%s/www/wp-content/uploads" % (repo, branch, repo, branch, build))
  with settings(hide('stderr'), warn_only=True):
    dirs = [ 'wflogs', 'w3tc-config', 'cache' ]
    for dirname in dirs:
      if run("stat /var/www/%s_%s_%s/www/wp-content/%s" % (repo, branch, build, dirname)).return_code == 0:
        sudo("mkdir -p /var/www/shared/%s_%s_%s" % (repo, branch, dirname))
        sudo("chown www-data:www-data /var/www/shared/%s_%s_%s" % (repo, branch, dirname))
        sudo("rm -rf /var/www/%s_%s_%s/www/wp-content/%s" % (repo, branch, build, dirname))
      run("ln -s /var/www/shared/%s_%s_%s /var/www/%s_%s_%s/www/wp-content/%s" % (repo, branch, dirname, repo, branch, build, dirname))

  with settings(warn_only=True):
    if run("stat /var/www/%s_%s_%s/www/wp-content/plugins/w3-total-cache/wp-content/advanced-cache.php" % (repo, branch, build)).failed:
      print "No advanced-cache.php file found. Continuing on with deployment."
    else:
      run("cp /var/www/%s_%s_%s/www/wp-content/plugins/w3-total-cache/wp-content/advanced-cache.php /var/www/%s_%s_%s/www/wp-content/advanced-cache.php" % (repo, branch, build, repo, branch, build))

    if run("stat /var/www/%s_%s_%s/www/wp-content/plugins/w3-total-cache/wp-content/object-cache.php" % (repo, branch, build)).failed:
      print "No object-cache.php file found. Continuing on with deployment."
    else:
      run("cp /var/www/%s_%s_%s/www/wp-content/plugins/w3-total-cache/wp-content/object-cache.php /var/www/%s_%s_%s/www/wp-content/object-cache.php" % (repo, branch, build, repo, branch, build))
