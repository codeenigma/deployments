from fabric.api import *

# Adjust the config.ini.php symlink
@task
@roles('app_all')
def adjust_config(repo, branch, build, www_root, application_directory):
  if run("stat %s/config/%s_%s.config.ini.php" % (www_root, repo, branch)):
    with settings(warn_only=True):
      print "Symlink in the config.ini.php file."
      if run("stat %s/%s_%s_%s/%s/config/config.ini.php" % (www_root, repo, branch, build, application_directory)).succeeded:
        run("mv %s/%s_%s_%s/%s/config/config.ini.php %s/%s_%s_%s/%s/config/unused.config.ini.php" % (www_root, repo, branch, build, application_directory, www_root, repo, branch, build, application_directory))
      
    if run("ln -s %s/config/%s_%s.config.ini.php %s/%s_%s_%s/%s/config/config.ini.php" % (www_root, repo, branch, www_root, repo, branch, build, application_directory)).failed:
      raise SystemExit("###### Couldn't symlink in config.ini.php settings. Aborting the build.")
  else:
    raise SystemExit("###### Couldn't find any config.ini.php. The Matomo site probably wasn't setup manually first. Aborting the build.")


# Adjust shared tmp sylink
@task
@roles('app_all')
def adjust_tmp_symlink(repo, branch, build, www_root, application_directory):
  print "Setting the tmp symlink."
  with settings(warn_only=True):
    if run("stat %s/%s_%s_%s/%s/tmp" % (www_root, repo, branch, build, application_directory)).succeeded:
      sudo("mv %s/%s_%s_%s/%s/tmp %s/%s_%s_%s/%s/tmp_old" % (www_root, repo, branch, build, application_directory, www_root, repo, branch, build, application_directory))
  sudo("ln -s %s/shared/%s_%s_tmp %s/%s_%s_%s/%s/tmp" % (www_root, repo, branch, www_root, repo, branch, build, application_directory))

