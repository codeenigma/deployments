from fabric.api import *
from fabric.contrib.files import *


@task
@roles('app_primary')
def adjust_parameters_yml(repo, buildtype, build):
  print "===> Adjusting parameters.yml..."
  with settings(warn_only=True):
    if run("stat /var/www/config/%s_%s.parameters.yml" % (repo, buildtype)).failed:
      print "No parameters.yml file, moving parameters.yml.dist to shared /var/www/config/%s_%s.parameters.yml. Database credentials will need adding." % (repo, buildtype)
      print "Any other secret data, API keys, passwords, etc. should be added to parameters_%s.yml in the repository." % (buildtype)
      # We copy parameters.yml.dist, which is an empty template, to /var/www/config/ ready to take database credentials.
      # Note, we cannot move the file because Symfony3+ expects it to exist, so we must copy.
      # This should be imported into app/config/parameters_ENV.yml in the repository and that file should contain other required secrets (API keys, etc.)
      sudo("cp /var/www/%s_%s_%s/app/config/parameters.yml.dist /var/www/config/%s_%s.parameters.yml" % (repo, buildtype, build, repo, buildtype))
      sudo("chown jenkins:www-data /var/www/config/%s_%s.parameters.yml" % (repo, buildtype))
      sudo("chmod 664 /var/www/config/%s_%s.parameters.yml" % (repo, buildtype))
      run("ln -s /var/www/config/%s_%s.parameters.yml /var/www/%s_%s_%s/app/config/parameters.yml" % (repo, buildtype, repo, buildtype, build))
    else:
      # Nothing to do, file already there.
      print "We found /var/www/config/%s_%s.parameters.yml so nothing to do except set up the link." % (repo, buildtype)
      run("ln -s /var/www/config/%s_%s.parameters.yml /var/www/%s_%s_%s/app/config/parameters.yml" % (repo, buildtype, repo, buildtype, build))


@task
@roles('app_all')
def adjust_env_file(repo, buildtype, build):
  with settings(warn_only=True):
    if run("stat /var/www/config/%s_%s.env" % (repo, buildtype)).failed:
      print "No .env file, moving .env.dist to shared /var/www/config/%s_%s.env. Secret data (database credentials, API keys, passwords, etc.) will need adding." % (repo, buildtype)
      print "Any other non-secret data should be added to the repository."
      # We copy .env.dist, which is a template, to /var/www/config/ ready to take secret data.
      # Note, we cannot move the file because Symfony3+ expects it to exist, so we must copy.
      # This should be loaded in the front controller and console in the repository.
      sudo("cp /var/www/%s_%s_%s/.env.dist /var/www/config/%s_%s.env" % (repo, buildtype, build, repo, buildtype))
      sudo("chown jenkins:www-data /var/www/config/%s_%s.env" % (repo, buildtype))
      sudo("chmod 664 /var/www/config/%s_%s.env" % (repo, buildtype))
      run("ln -s /var/www/config/%s_%s.env /var/www/%s_%s_%s/.env" % (repo, buildtype, repo, buildtype, build))
    else:
      # Nothing to do, file already there.
      print "We found /var/www/config/%s_%s.env so nothing to do except set up the link." % (repo, buildtype)
      run("ln -s /var/www/config/%s_%s.env /var/www/%s_%s_%s/.env" % (repo, buildtype, repo, buildtype, build))
