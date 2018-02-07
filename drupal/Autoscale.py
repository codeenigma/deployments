from fabric.api import *

@task
@roles('app_all')
def remove_original_settings_files(repo, site):
  with settings(warn_only=True):
    run("rm -R /var/www/%s/www/sites/%s/*.settings.php" % (repo, site))
    print "===> Removed *.settings.php from initial autoscale app folders"
