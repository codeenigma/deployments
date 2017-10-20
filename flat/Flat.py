from fabric.api import *
from fabric.contrib.files import *

@task
def symlink_assets(repo, branch, build):
  with settings(warn_only=True):
    items = ['css', 'js', 'images']
    for item in items:
      print "===> Creating a symlink to assets/%s directory" % (item)
      if sudo("ln -s /var/www/%s_%s_%s/assets/%s /var/www/%s_%s_%s/build/%s" % (repo, branch, build, item, repo, branch, build, item)).failed:
        print "Could not create symlink to %s directory!" % (item)
        raise SystemExit("Could not create symlink to %s directory!" % (item))
