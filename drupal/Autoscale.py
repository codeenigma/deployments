from fabric.api import *

@task
@roles('app_all')
def remove_original_settings_files(repo):
  with settings(warn_only=True):
    run("rm -R /var/www/%s/www/sites/default/*.settings.php" % repo)
    print "===> Removed *.settings.php from initial autoscale app folders"
