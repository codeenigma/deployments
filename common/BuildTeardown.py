from fabric.api import *
import random
import string
import os


@task
def remove_vhost(repo, branch, webserver, alias):
  if alias is None:
    alias = repo
  with settings(warn_only=True):
    print "===> Unlinking and removing %s vhost..." % webserver
    # We grep the config files for the correct symlink to be sure we delete the right one
    conf_file = sudo("find /etc/%s/sites-enabled/ -name '*%s*' -print0 | xargs -r -0 grep -H 'live.%s.%s' | head -1 | awk '{print $1}' | cut -d '/' -f 5 | cut -d ':' -f 1" % (webserver, alias, repo, branch))

    print "%s conf file is: %s" % (webserver, conf_file)
    sudo("unlink /etc/%s/sites-enabled/%s" % (webserver, conf_file))
    sudo("rm /etc/%s/sites-available/%s" % (webserver, conf_file))

@task
def remove_http_auth(repo, branch, webserver, alias=None):
  if alias is None:
    alias = repo
  print "=> Removing htpasswd file, if it exists..."
  with settings(warn_only=True):
    if sudo("stat /etc/%s/passwords/%s.%s.htpasswd" % (webserver, alias, branch)).failed:
      print "===> No htpasswd file to remove. Carrying on with tear down."
    else:
      sudo("rm /etc/%s/passwords/%s.%s.htpasswd" % (webserver, alias, branch))

@task
def remove_cron(repo, branch, alias=None):
  if alias is None:
    alias = repo
  with settings(warn_only=True):
    print "===> Removing cron file..."
    sudo("rm /etc/cron.d/%s_%s_cron" % (alias, branch))
