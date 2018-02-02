from fabric.api import *
import random
import string
import os


@task
def remove_vhost(repo, branch, webserver, url):
  with settings(warn_only=True):
    print "===> Unlinking and removing %s vhost..." % webserver
    # We search for and grep the config to be sure we haven't been passed a bad url
    conf_file = sudo("find /etc/%s/sites-enabled/ -name '%s.conf' -print0 | xargs -r -0 grep 'live.%s.%s' | awk '{print $2}' | cut -d '/' -f 4 | cut -d ':' -f 1" % (webserver, url, repo, branch))
    print "%s conf file is: %s" % (webserver, conf_file)
    sudo("unlink /etc/%s/sites-enabled/%s" % (webserver, conf_file))
    sudo("rm /etc/%s/sites-available/%s" % (webserver, conf_file))

@task
def remove_http_auth(repo, branch, webserver):
  print "===> Removing htpasswd file, if it exists..."
  with settings(warn_only=True):
    if sudo("stat /etc/%s/passwords/%s.%s.htpasswd" % (webserver, repo, branch)).failed:
      print "No htpasswd file to remove. Carrying on with tear down."
    else:
      sudo("rm /etc/%s/passwords/%s.%s.htpasswd" % (webserver, repo, branch))

@task
def remove_cron(repo, branch):
  with settings(warn_only=True):
    print "===> Removing cron file..."
    sudo("rm /etc/cron.d/%s_%s_cron" % (repo, branch))