from fabric.api import *
from fabric.contrib.files import *
import random
import string
import os
import time
import uuid
# Import AWS tools
import boto3
# Custom Code Enigma modules
import common.ConfigFile


# Helper function.
# Runs a command with SSH agent forwarding enabled.
# At time of writing, Fabric (and paramiko) can't forward your SSH agent.
@task
def _sshagent_run(cmd, ssh_key=None):
  # catch the port number to pass to ssh
  if ssh_key is None:
    print local('ssh-agent bash -c \'ssh-add; ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -t -A %s "%s"\'' % (env.host, cmd))
  else:
    if local("stat %s" % ssh_key).failed:
      raise SystemExit("===> No ssh key found at %s on the server. Aborting." % ssh_key)
    else:
      # A different key has been specified, we need to add to the agent in order to carry out this command
      print local('ssh-agent bash -c \'ssh-add %s; ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -t -A %s "%s"\'' % (ssh_key, env.host, cmd))


# Helper script to generate a random password
@task
def _gen_passwd(N=8):
  return ''.join(random.choice(string.ascii_letters + string.digits) for x in range(N))


# Helper script to generate a random token
@task
def _gen_token():
  return uuid.uuid4().hex


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
def clone_repo(repo, repourl, branch, build, buildtype=None, ssh_key=None):
  if buildtype == None:
    cleanbranch = branch.replace('/', '-')

    print "===> Cloning %s from %s" % (repo, repourl)
    _sshagent_run("git clone --branch %s %s ~jenkins/%s_%s_%s" % (branch, repourl, repo, cleanbranch, build), ssh_key)

    with settings(warn_only=True):
      if run("ls -1 ~jenkins/%s_%s_%s" % (repo, cleanbranch, build)).failed:
        raise SystemExit("Could not clone the repository to create a new build! Aborting")
    with settings(warn_only=True):
      if sudo("mv ~jenkins/%s_%s_%s /var/www" % (repo, cleanbranch, build)).failed:
        raise SystemExit("Could not move the build into place in /var/www/! Aborting")
  else:
    print "===> Cloning %s from %s" % (repo, repourl)
    _sshagent_run("git clone --branch %s %s ~jenkins/%s_%s_%s" % (branch, repourl, repo, buildtype, build), ssh_key)

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
  # Use branch as buildtype if none provided
  if buildtype == None:
    print "===> No buildtype provided, using branch name %s instead" % branch
    buildtype = branch

  # Checking for a symlink, in certain edge cases there may not be one
  with settings(warn_only=True):
    if run("stat /var/www/live.%s.%s" % (repo, buildtype)).succeeded:
      print "===> Removing current symlink to previous live codebase"
      sudo("unlink /var/www/live.%s.%s" % (repo, buildtype))

  print "===> Setting new symlink to new live codebase"
  sudo("ln -s /var/www/%s_%s_%s /var/www/live.%s.%s" % (repo, buildtype, build, repo, buildtype))


@task
def statuscake_state(statuscakeuser, statuscakekey, statuscakeid, state=""):
  with settings(warn_only=True):
    if state == "pause":
      # If we have StatusCake information, pause the checks
      if statuscakekey is not None:
        if statuscakeid is not None:
          print "===> Pausing StatusCake job with ID %s" % statuscakeid
          run('curl -H "API: %s" -H "Username: %s" -d "TestID=%s&Paused=1" -X PUT https://app.statuscake.com/API/Tests/Update' % (statuscakekey, statuscakeuser, statuscakeid))
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
          if run('curl -H "API: %s" -H "Username: %s" -d "TestID=%s&Paused=0" -X PUT https://app.statuscake.com/API/Tests/Update' % (statuscakekey, statuscakeuser, statuscakeid)).failed:
            print "Failed to resume the StatusCake job with ID %s. You will need to resume it manually." % statuscakeid
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
def define_roles(config, cluster, autoscale=None, aws_credentials='/home/jenkins/.aws/credentials', aws_autoscale_group='prod-asg-prod'):
  # Catch people who've set both cluster and autoscale, can't be both!
  if cluster and autoscale:
    raise SystemError("### You cannot be BOTH a traditional cluster AND an autoscale build. Aborting!")

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

  elif autoscale:
    # Load in AWS credentials from autoscale variable
    aws_config = common.ConfigFile.read_config_file(aws_credentials, abort_if_missing=True, fullpath=True)
    # Blank the apps array, just in case
    all_apps = []
    # Make sure we have AWS credentials
    if aws_config.has_section(autoscale):
      print "===> We have AWS credentials for %s" % autoscale
      aws_region = aws_config.get(autoscale, "region")
    else:
      raise SystemError("### Autoscale build but no credentials found for %s. Aborting!" % autoscale)
    # Set up our AWS CLI sessions
    session = boto3.Session(profile_name=autoscale, region_name=aws_region)
    ec2_client = session.client('ec2', region_name=aws_region)
    as_client = session.client('autoscaling', region_name=aws_region)

    # Get AutoScaling Group
    groups = as_client.describe_auto_scaling_groups()
    # Filter for instances only in an ASG that matches our project name, as passed in above
    for group in groups['AutoScalingGroups']:
      if group['AutoScalingGroupName'].startswith(aws_autoscale_group):
        # Get a list of DNS names of instances in the autoscale group
        for instance in group['Instances']:
          response = ec2_client.describe_instances(InstanceIds = [instance['InstanceId']])
          all_apps.append(response['Reservations'][0]['Instances'][0]['NetworkInterfaces'][0]['PrivateIpAddress'])
    if all_apps:
      all_apps.sort()
      # Set up roles
      env.roledefs = {
        'app_all': all_apps,
        'app_primary': [ all_apps[0] ],
      }

      # Autoscale config overwrites host data so we need to set it
      env.host = all_apps[0]
      print "===> Host is %s" % env.host
    else:
      raise SystemError("### Autoscale build but no servers found for cluster named %s with credentials for %s. Aborting!" % (aws_autoscale_group, autoscale))

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
# Note, the dummy vhosts need to already exist - this function is currently only used from
# within initial_build_vhost() which handles copying the dummy vhosts to the server(s).
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


# Zip up and password protect a file, then upload it to an S3 bucket
@task
def s3_upload(shortname, branch, method, file_name, bucket_name, tmp_dir="s3-uploads", region="eu-west-1"):
  zip_password = _gen_passwd()
  zip_token = _gen_token()
  now = time.strftime("%Y%m%d%H%M%S", time.gmtime())

  upload_to_s3 = False

  method = check_package(method)

  with lcd("/tmp/%s" % tmp_dir):
    if method == "7zip":
      print "===> Zipping up file with 7zip..."
      if local("7za a -tzip -p%s -mem=AES256 %s-%s_%s%s-%s.zip %s-%s_%s.sql.bz2" % (zip_password, shortname, branch, file_name, now, zip_token, shortname, branch, file_name)).failed:
        print "ERROR: Could not zip up file using 7zip. Contact a system administrator."
        raise SystemError("Could not zip up file using 7zip. Contact a system administrator.")
      else:
        print "SUCCESS: File has been zipped up. You will need to extract it using 7za e FILENAME and entering the password (which will be provided down below if all else goes well), when prompted."
        upload_to_s3 = True
    elif method == "zip":
      print "===> Zipping up file with zip..."
      if local("zip -P %s %s-%s_%s%s-%s.zip %s-%s_%s.sql.bz2" % (zip_password, shortname, branch, file_name, now, zip_token, shortname, branch, file_name)).failed:
        print "ERROR: Could not zip up file using zip. Contact a system administrator."
        raise SystemError("Could not zip up file using zip. Contact a system administrator.")
      else:
        print "SUCCESS: File has been zipped up. You will need to extract it using unzip FILENAME and entering the password (which will be provided down below if all else goes well), when prompted."
        upload_to_s3 = True
    else:
      print "ERROR: Invalid method chosen."

  if upload_to_s3 == False:
    print "There were previous errors, so aborting!"
    raise SystemError("There were previous errors, so aborting!")
  else:
    print "===> Uploading %s %s file to an S3 bucket." % (shortname, branch)
    local("sudo s3cmd put /tmp/%s/%s-%s_%s%s-%s.zip s3://%s/%s-%s_%s%s-%s.zip" % (tmp_dir, shortname, branch, file_name, now, zip_token, bucket_name, shortname, branch, file_name, now, zip_token))

    # Remove file from /tmp
    local("sudo rm -f /tmp/%s/%s-%s_%s%s-%s.zip" % (tmp_dir, shortname, branch, file_name, now, zip_token))
    local("sudo rm -f /tmp/%s/%s-%s_%s.sql.bz2" % (tmp_dir, shortname, branch, file_name))

    print "===> File uploaded! Please find details below to download and extract the file. The file will be deleted in 7 days as of now."
    # @TODO
    print "S3 bucket URL: https://s3-%s.amazonaws.com/%s/%s-%s_%s%s-%s.zip" % (region, bucket_name, shortname, branch, file_name, now, zip_token)
    print "Zip password: %s" % zip_password


# Helper function to ensure a zip method exists on a Jenkins server
@task
def check_package(method):
  supported_methods = ['zip', '7zip']
  # Check if the method selected is actually supported by this script
  if method not in supported_methods:
    print "ERROR: Woah, the method %s is not supported by this script. Contact a system administrator. Aborting build." % method
    raise SystemError("Woah, the method %s is not supported by this script. Contact a system administrator. Aborting build." % method)
  else:
    print "===> First, check that %s exists on the Jenkins server..." % method
    if method == "7zip":
      dpkg_check = 'p7zip-full'
      fallback_method = 'zip'
    else:
      dpkg_check = method
      fallback_method = 'p7zip-full'

    with settings(warn_only=True):
      if local("dpkg -s %s | grep 'install ok'" % dpkg_check).return_code != 0:
        print "ERROR: The selected method, %s, could not be found on the server. Checking fallback method..." % method
        if local("dpkg -s %s | grep 'install ok'" % fallback_method). return_code != 0:
          print "ERROR: The fallback method, %s, also could not be found. Aborting build." % fallback_method
          raise SystemError("The chosen method, %s, and the fallback method, %s, both could not be found. Aborting build." % (method, fallback_method))
        else:
          print "Fallback method, %s, found. Using that to compress and password protect file." % fallback_method
          method = fallback_method
      else:
        print "Chosen method, %s, found. Using that to compress and password protect file." % method

    return method


# Tarball up an application for future fresh EC2 instances entering an autoscale group
@task
@roles('app_primary')
def tarball_up_to_s3(repo, buildtype, build, autoscale):
  with cd("/var/www/%s_%s_%s" % (repo, buildtype, build)):
    print("===> Tarballing up the build to S3 for future EC2 instances")
    sudo("rm -f /tmp/%s.tar.gz" % repo)
    run("tar -zcf /tmp/%s.tar.gz ." % repo)
    run('export AWS_PROFILE="%s"' % repo)
    run("sudo /usr/local/bin/aws s3 cp /tmp/%s.tar.gz s3://current-%s-production" % (repo, autoscale))
    sudo("rm -f /tmp/%s.tar.gz" % repo)
