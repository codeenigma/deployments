from fabric.api import *
from fabric.contrib.files import *
import random
import string
import os
import time
# Custom Code Enigma modules
import common.ConfigFile


# Helper function.
# Runs a command with SSH agent forwarding enabled.
# At time of writing, Fabric (and paramiko) can't forward your SSH agent.
@task
def _sshagent_run(cmd):
  # catch the port number to pass to ssh
  if "git@github.com" in cmd:
    # These repos are at github, for which we have a different key we need to add to the agent in order to clone them
    print local('ssh-agent bash -c \'ssh-add /var/lib/jenkins/.ssh/id_rsa_github; ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -t -A %s "%s"\'' % (env.host, cmd))
  else:
    print local('ssh-agent bash -c \'ssh-add; ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -t -A %s "%s"\'' % (env.host, cmd))


# Helper script to generate a random password
@task
def _gen_passwd(N=8):
  return ''.join(random.choice(string.ascii_letters + string.digits) for x in range(N))


# Generate a timestamp for NOW
@task
def _gen_datetime():
  datetime = time.strftime("%Y%m%d%H%M%S", time.gmtime())
  return datetime


# Generate the branch name centrally
@task
def generate_branch_name(branch):
  branch = branch.replace('/', '-')
  return branch


# Generate and/or clean URL centrally
@task
def generate_url(url, repo, branch):
  if url is None:
    url = "%s.%s.%s" % (repo, branch, env.host)
  url = url.replace('/', '-')
  url_output = url.lower()
  return url_output


# Tasks for getting previous build strings for path and database
@task
def get_previous_build(repo, branch, build):
  return run("readlink /var/www/live.%s.%s" % (repo, branch))

@task
def get_previous_db(repo, branch, build):
  return "~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz" % (repo, branch, build)


# Git clone the repo to /var/www/project_branch_build_BUILDID
@task
def clone_repo(repo, repourl, branch, build, buildtype=None):
  if buildtype == None:
    cleanbranch = branch.replace('/', '-')
    print "===> Cloning %s from %s" % (repo, repourl)
    _sshagent_run("git clone --branch %s %s ~jenkins/%s_%s_%s" % (branch, repourl, repo, cleanbranch, build))
    with settings(warn_only=True):
      if run("ls -1 ~jenkins/%s_%s_%s" % (repo, cleanbranch, build)).failed:
        raise SystemExit("Could not clone the repository to create a new build! Aborting")
    with settings(warn_only=True):
      if sudo("mv ~jenkins/%s_%s_%s /var/www" % (repo, cleanbranch, build)).failed:
        raise SystemExit("Could not move the build into place in /var/www/! Aborting")
  else:
    print "===> Cloning %s from %s" % (repo, repourl)
    _sshagent_run("git clone --branch %s %s ~jenkins/%s_%s_%s" % (branch, repourl, repo, buildtype, build))
    with settings(warn_only=True):
      if run("ls -1 ~jenkins/%s_%s_%s" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not clone the repository to create a new build! Aborting")
    with settings(warn_only=True):
      if sudo("mv ~jenkins/%s_%s_%s /var/www" % (repo, buildtype, build)).failed:
        raise SystemExit("Could not move the build into place in /var/www/! Aborting")


# Remove old builds to conserve disk space
@task
def remove_old_builds(repo, branch, keepbuilds, buildtype=None):
  print "===> Removing all but the last %s builds to conserve disk space" % keepbuilds
  # Copy remove builds script to server(s)
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/remove_old_builds.sh', '/home/jenkins', mode=0755).failed:
    raise SystemExit("Could not copy the remove builds script to the application server, aborting so it's clear there was a problem, even though this is the last step")
  else:
    print "===> Remove builds script copied to %s:/home/jenkins/remove_old_builds.sh" % env.host

  if buildtype == None:
    sudo("/home/jenkins/remove_old_builds.sh -d /var/www -r %s -b %s -k %s" % (repo, branch, keepbuilds))
  else:
    sudo("/home/jenkins/remove_old_builds.sh -d /var/www -r %s -b %s -k %s" % (repo, buildtype, keepbuilds))


# Adjust symlink in /var/www/project to point to the new build
# this happens after database changes have been applied in drush_updatedb()
@task
def adjust_live_symlink(repo, branch, build, buildtype=None):
  print "===> Removing current symlink to previous live codebase"
  if buildtype == None:
    sudo("unlink /var/www/live.%s.%s" % (repo, branch))
  else:
    sudo("unlink /var/www/live.%s.%s" % (repo, buildtype))

  print "===> Setting new symlink to new live codebase"
  if buildtype == None:
    sudo("ln -s /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, branch, build, repo, branch))
  else:
    sudo("ln -s /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, buildtype, build, repo, buildtype))


@task
def statuscake_state(statuscakekey, statuscakeid, state=""):
  if state == "pause":
    # If we have StatusCake information, pause the checks
    if statuscakekey is not None:
      if statuscakeid is not None:
        print "===> Pausing StatusCake job with ID %s" % statuscakeid
        run('curl -H "API: %s" -H "Username: codeenigma" -d "TestID=%s&Paused=1" -X PUT https://app.statuscake.com/API/Tests/Update' % (statuscakekey, statuscakeid))
        # Return a boolean to raise the statuscake_paused flag
        return True
      else:
        print "===> StatusCake ID not available, cannot pause checks."
    else:
      print "===> No StatusCake information provided, skipping check pausing step."
  else:
    if statuscakekey is not None:
      if statuscakeid is not None:
        # Default action, resume the checks
        print "===> Resuming StatusCake job with ID %s" % statuscakeid
        run('curl -H "API: %s" -H "Username: codeenigma" -d "TestID=%s&Paused=0" -X PUT https://app.statuscake.com/API/Tests/Update' % (statuscakekey, statuscakeid))
  # Catch all return value so we cannot set statuscake_paused to an ambiguous value
  return False


# Extract the primary host from config.ini
@task
def define_host(config, buildtype, repo):
  # We need to iterate through the options in the map and find the right host based on
  # whether the repo name matches any of the options, as they may not be exactly identical
  if config.has_section(buildtype):
    for option in config.options(buildtype):
       line = config.get(buildtype, option)
       line = line.split(',')
       for entry in line:
         if option.strip() in repo:
           env.host = entry.strip()
           print "===> Host is %s" % env.host
           break


# Configure server roles for clusters (if applicable)
@task
def define_roles(config, cluster):
  # Need to set up server roles for clusters
  if cluster:
    print "===> This is a cluster, setting up server roles"
    # Form a list of our apps from the config.ini
    all_apps = []
    apps = config.items('Apps')
    for key, value in apps:
      all_apps.append(value)
    #Commenting out app sorting as it sorts by value, which is painful when app2 == 172.30.4.141 and app1 == 172.30.4.240 (OOTB example)
    #all_apps.sort()

    all_apps_ips = []
    if config.has_section('AppIPs'):
      apps_ips = config.items('AppIPs')
      for key, value in apps_ips:
        all_apps_ips.append(value)

    # Form a list of our dbs from the config.ini
    all_dbs = []
    dbs = config.items('Dbs')
    for key, value in dbs:
      all_dbs.append(value)
    all_dbs.sort()

    # Form a list of our memcaches from the config.ini
    all_memcaches = []
    memcaches = config.items('Memcaches')
    for key, value in memcaches:
      all_memcaches.append(value)
    all_memcaches.sort()

    env.roledefs = {
        'app_all': all_apps,
        'app_ip_all': all_apps_ips,
        'db_all': all_dbs,
        'app_primary': [ all_apps[0] ],
        'app_ip_primary': [ all_apps_ips[0] ],
        'db_primary': [ all_dbs[0] ],
        # No such thing as a 'primary' memcache, really..
        'memcache_all': all_memcaches,
    }

    # Cluster config script overwrites host data so we need to set it
    env.host = all_apps[0]
    print "===> Host is %s" % env.host

  # Not a cluster, so give all roles to single host
  else:
    print "===> This is *NOT* a cluster, setting all server roles to %s" % env.host
    env.roledefs = {
        'app_all': [ env.host ],
        'db_all': [ env.host ],
        'app_primary': [ env.host ],
        'db_primary': [ env.host ],
        'memcache_all': [ env.host ],
    }

# Creating required application directories
@task
def create_config_directory():
  with settings(warn_only=True):
    if run("stat /var/www/config").failed:
      # No "config" directory
      sudo("mkdir --mode 0755 /var/www/config")
      sudo("chown jenkins:www-data /var/www/config")
      print "===> Config directory created"
    else:
      print "===> Config directory already exists"

@task
def create_shared_directory():
  with settings(warn_only=True):
    if run("stat /var/www/shared").failed:
      # No "config" directory
      sudo("mkdir --mode 0755 /var/www/shared")
      sudo("chown jenkins:www-data /var/www/shared")
      print "===> Shared directory created"
    else:
      print "===> Shared directory already exists"

@task
def perform_client_deploy_hook(repo, branch, build, buildtype, config, stage):
  cwd = os.getcwd()
  print "===> Looking for custom developer hooks at the %s stage for %s builds" % (stage, buildtype)

  malicious_commands = ['env.host_string', 'env.host', 'rm -rf /', 'ssh']

  if config.has_section("%s-%s-build" % (buildtype, stage)):
    print "===> Found %s-%s-build hooks, executing" % (buildtype, stage)
    for option in config.options("%s-%s-build" % (buildtype, stage)):
      if config.getint("%s-%s-build" % (buildtype, stage), option) != 1:
        print "Skipping %s hook file because it is not set to 1 in config.ini." % option
      else:
        malicious_code = False
        with settings(warn_only=True):
          for disallowed in malicious_commands:
            if run("grep '%s' /var/www/%s_%s_%s/build-hooks/%s" % (disallowed, repo, branch, build, option)).return_code == 0:
              print "We found %s in the %s file, so as a result, we are not running that hook file." % (disallowed, option)
              malicious_code = True
              break

        if not malicious_code:
          if option[-2:] == 'sh':
            print "===> Executing shell script %s" % option

            run("chmod +x /var/www/%s_%s_%s/build-hooks/%s" %(repo, branch, build, option))
            if stage != 'pre':
              with settings(warn_only=True):
                if run("/var/www/%s_%s_%s/build-hooks/%s" %(repo, branch, build, option)).failed:
                  print "Could not run build hook. Uh oh."
                else:
                  print "Finished running build hook."
            else:
              if run("/var/www/%s_%s_%s/build-hooks/%s" %(repo, branch, build, option)).failed:
                print "Could not run build hook. Uh oh."
              else:
                print "Finished running build hook."

          if option[-2:] == 'py':
            print "===> Executing Fabric script %s" % option
            hook_file = '%s/build-hooks/%s' % (cwd, option)

            if stage != 'pre':
              with settings(warn_only=True):
                if local("fab -H %s -f %s main:repo=%s,branch=%s,build=%s" % (env.host, hook_file, repo, branch, build)).failed:
                  print "Could not run build hook. Uh oh."
                else:
                  print "Finished running build hook."
            else:
              if local("fab -H %s -f %s main:repo=%s,branch=%s,build=%s" % (env.host, hook_file, repo, branch, build)).failed:
                print "Could not run build hook. Uh oh."
              else:
                print "Finished running build hook."


@task
def perform_client_sync_hook(path_to_application, buildtype, stage):
  print "===> Looking for custom developer hooks at the %s stage of this sync from %s" % (stage, buildtype)

  malicious_commands = ['env.host_string', 'env.host', 'rm -rf /', 'ssh']

  application_config_path = path_to_application + '/config.ini'
  print "===> Trying to read config at %s" % application_config_path
  application_config = common.ConfigFile.read_config_file(application_config_path, False, True, True)
  print "===> This hook is %s-%s-sync"  % (buildtype, stage)

  with settings(warn_only=True):
    if application_config.has_section("%s-%s-sync" % (buildtype, stage)):
      print "===> Found %s-%s-sync hooks, executing" % (buildtype, stage)
      for option in application_config.options("%s-%s-sync" % (buildtype, stage)):
        if application_config.getint("%s-%s-sync" % (buildtype, stage), option) != 1:
          print "Skipping %s hook file because it is not set to 1 in config.ini." % option
        else:
          malicious_code = False
          with settings(warn_only=True):
            for disallowed in malicious_commands:
              if run("grep '%s' %s/build-hooks/%s" % (disallowed, path_to_application, option)).return_code == 0:
                print "We found %s in the %s file, so as a result, we are not running that hook file." % (disallowed, option)
                malicious_code = True
                break
  
          if not malicious_code:
            if option[-2:] == 'sh':
              print "===> Executing shell script %s" % option
  
              run("chmod +x %s/build-hooks/%s" %(path_to_application, option))
              if stage != 'pre':
                with settings(warn_only=True):
                  if run("%s/build-hooks/%s" %(path_to_application, option)).failed:
                    print "Could not run build hook. Uh oh."
                  else:
                    print "Finished running build hook."
              else:
                if run("%s/build-hooks/%s" %(path_to_application, option)).failed:
                  print "Could not run build hook. Uh oh."
                else:
                  print "Finished running build hook."
    else:
      print "===> No sync hooks found"
# @TODO: Not supporting Fabric on syncs for now
#          if option[-2:] == 'py':
#            print "===> Executing Fabric script %s" % option
#            hook_file = '%s/build-hooks/%s' % (cwd, option)

#            if stage != 'pre':
#              with settings(warn_only=True):
#                if local("fab -H %s -f %s main:repo=%s,branch=%s,build=%s" % (env.host, hook_file, repo, branch, build)).failed:
#                  print "Could not run build hook. Uh oh."
#                else:
#                  print "Finished running build hook."
#            else:
#              if local("fab -H %s -f %s main:repo=%s,branch=%s,build=%s" % (env.host, hook_file, repo, branch, build)).failed:
#                print "Could not run build hook. Uh oh."
#              else:
#                print "Finished running build hook."


# Protecting a vhost with a username and password.
@task
def create_httpauth(webserver, repo, branch, url, httpauth_pass):
  with settings(warn_only=True):
    if sudo("stat /etc/%s/passwords/%s.%s.htpasswd" % (webserver, repo, branch)).failed:
      print "===> Could not find /etc/%s/passwords/%s.%s.htpasswd, so creating one..." % (webserver, repo, branch)
      if webserver == "nginx":
        script_dir = os.path.dirname(os.path.realpath(__file__))
        if put(script_dir + '/../util/nginx.htpasswd', '/home/jenkins', mode=0755).failed:
          print "===> Could not copy the nginx.htpasswd script to the application server, http auth will not be set up"
        else:
          print "===> nginx.httpasswd script copied to %s:/home/jenkins/nginx.htpasswd" % env.host
          sudo("/home/jenkins/nginx.htpasswd %s %s %s" % (repo, httpauth_pass, branch))
          print "***** HTTP auth set up; user/pass is %s / %s *****" % (repo, httpauth_pass)

        # Use the sed() function to replace the commented out HTTP auth options in the nginx
        # dummy file
        # First, define where the vhost is
        vhost = "/etc/%s/sites-available/%s.conf" % (webserver, url)
        # Set the variables for the search and replace values
        auth_basic = "#auth_basic"
        auth_basic_replace = "auth_basic"
        # Replace the #auth_basic line with auth_basic, so HTTP auth is enabled
        sed(vhost, auth_basic, auth_basic_replace, limit='', use_sudo=True, backup='', flags="i", shell=False)
        auth_basic_user_file = "#auth_basic_user_file"
        auth_basic_user_file_replace = "auth_basic_user_file"
        # Replace the #auth_basic_user_file with auth_basic_user_file, so we're setting the
        # path to the file with HTTP auth credentials
        sed(vhost, auth_basic_user_file, auth_basic_user_file_replace, limit='', use_sudo=True, backup='', flags="i", shell=False)
