from fabric.api import *
from fabric.contrib.files import *
import random
import string


# Merge production branch in
# Note: could make prod a config parameter later
@task
def merge_prod(repo, branch, build):
  print "===> Merging prod into %s" % (branch)
  with cd("/var/www/%s_%s_%s" % (repo, branch, build)):
    with settings(warn_only=True):
      if run("git merge -m 'Automatic updates by Jenkins.' remotes/origin/prod").failed:
        print "Git merge failed!"
        raise SystemExit("Could not merge the production branch! Aborting")


# Drush update the modules we want to update (requires Nagios module)
# Note: at the moment this pulls 'all' but there's a security only option we could implement
@task
def drush_up(repo, branch):
  with cd("/var/www/live.%s.%s/www" % (repo, branch)):
    print "===> Clearing Drupal cache"
    run ("drush cc all")
    print "===> Forcing an update check to be sure"
    run ("drush php-eval 'update_refresh(); update_fetch_data();'")
    print "===> Updating out of date modules"
    module_updates = filter(None, run("drush nagios-updates").split(' '))
    if not module_updates:
      print "No modules set for update, not doing anything!"
    else:
      for module in module_updates:
        with settings(warn_only=True):
          if run("drush -y up %s" % module).failed:
            print "Drush update failed!"
            raise SystemExit("Could not Drush update! Aborting")
          else:
            print "===> Adding changes for %s to %s branch" % (module, branch)
            run("git add $(git status -s | grep -v ^' D' | awk {'print $2'}) && git commit -m 'Updated %s'" % module)


# Add the updates to the branch and push
@task
def add_push_updates(repo, branch, build):
  with cd("/var/www/%s_%s_%s" % (repo, branch, build)):
    # Set things up so sysadmins can push changes
    sudo("chown -Rf jenkins:sysadmins ./")
    sudo("chmod -Rf g+w ./")
######################
# HAVING TROUBLE WITH THIS - Jenkins can't push
# See: https://jenkins.codeenigma.com/job/Deploy_codeenigma-new_hotfixes_branch/9/console
######################
    print "===> Pushing changes to central repository for %s branch" % (branch)
    _sshagent_run("cd /var/www/%s_%s_%s && git push origin %s --force" % (repo, branch, build, branch))


# Send update notification by email
@task
def send_update_notification(repo, branch):
  print "===> Sending email to support team"
  local("echo 'New updates for project %s deployed by Jenkins on %s. You can check the site at: http://%s.%s.%s' | mail -s 'New updates' updates@codeenigma.com" % (repo, env.host, repo, branch, env.host))

