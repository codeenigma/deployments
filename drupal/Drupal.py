from fabric.api import *
from fabric.contrib.files import *
import random
import string
import datetime
# Custom Code Enigma modules
import DrupalUtils
import DrupalConfig
import common.ConfigFile
import common.Services
import common.Utils
import common.MySQL
import Revert


# Function to set up a site mapping for Drupal multisites, if applicable.
@task
def configure_site_mapping(repo, mapping, config, method="deployment", branch=None):
  wording = []
  if method == "deployment":
    wording = ["deploy", "deployment"]
  else:
    wording = ["sync", "sync"]
  sites = []
  # [Sites] is defined in config.ini
  if config.has_section("Sites"):
    print "===> Found a Sites section. Determining which sites to %s..." % wording[0]
    for option in config.options("Sites"):
      line = config.get("Sites", option)
      line = line.split(',')
      for sitename in line:
        sitename = sitename.strip()
        sites.append(sitename)

  if not sites:
    print "There isn't a Sites section, so we assume this is standard %s." % wording[1]
    buildsite = 'default'
    alias = repo
    mapping.update({alias:buildsite})
  # @TODO: can this use sites.php?
  else:
    if method == "deployment":
      dirs = os.walk('www/sites').next()[1]
    else:
      if branch is None:
        raise SystemExit("Cannot configure a sync mapping if the branch name hasn't been specified.")
      dirs = []
      dirs_remote = run("cd /var/www/live.%s.%s/www/sites && ls -d */" % (repo, branch))
      print "dirs_remote: %s" % dirs_remote
      dir_array = dirs_remote.split('/')
      for directory in dir_array:
        directory = directory.strip()
        if directory:
          dirs.append(directory)
      print "dirs: %s" % dirs
    for buildsite in dirs:
      if buildsite in sites:
        if buildsite == 'default':
          alias = repo
        else:
          alias = "%s_%s" % (repo, buildsite)
        mapping.update({alias:buildsite})

  print "Final mapping is: %s" % mapping
  return mapping


@task
def drush_fra_branches(config, branch):
  # @TODO temporary, this can go once nobody uses [Features] in config.ini any more
  # If a 'branches' option exists in the [Features] section in config.ini, proceed
  # THIS IS DEPRECATED
  feature_branches = common.ConfigFile.return_config_item(config, "Features", "branches", "string", None, True, True, "Drupal")

  if feature_branches is not None:
    revert_branches = []
    if feature_branches == "*":
      revert_branches.append(branch)
    else:
      feature_branches = feature_branches.split(',')
      for each_branch in feature_branches:
        each_branch = each_branch.strip()
        revert_branches.append(each_branch)
  else:
    revert_branches = ['master', 'stage']

  # If a 'feature_branches' option exists in the [Build] section in config.ini, proceed
  # THIS IS DEPRECATED
  feature_branches = common.ConfigFile.return_config_item(config, "Build", "feature_branches", "string", None, True, True, "Drupal")

  if feature_branches is not None:
    revert_branches = []
    if feature_branches == "*":
      revert_branches.append(branch)
    else:
      feature_branches = feature_branches.split(',')
      for each_branch in feature_branches:
        each_branch = each_branch.strip()
        revert_branches.append(each_branch)
  else:
    revert_branches = ['master', 'stage']

  # If a 'feature_branches' option exists in the [Drupal] section in config.ini, proceed
  feature_branches = common.ConfigFile.return_config_item(config, "Drupal", "feature_branches", "string", None, True, False)

  if feature_branches is not None:
    revert_branches = []
    if feature_branches == "*":
      revert_branches.append(branch)
    else:
      feature_branches = feature_branches.split(',')
      for each_branch in feature_branches:
        each_branch = each_branch.strip()
        revert_branches.append(each_branch)
  else:
    revert_branches = ['master', 'stage']

  return revert_branches


# Get the database name of an existing Drupal website
@task
@roles('app_primary')
def get_db_name(repo, branch, build, buildtype, site, drush_output):
  db_name = None
  db_name = run("echo \"%s\" | grep \"db-name: \" | cut -d \":\" -f 2" % drush_output)

  # If the dbname variable is empty for whatever reason, resort to grepping settings.php
  if not db_name:
    with cd("/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)):
      print "===> drush did not give us a database name so grepping the settings file"
      db_name = sudo("grep \"'database' => '%s*\" settings.php | cut -d \">\" -f 2" % repo)
      db_name = db_name.translate(None, "',")
  print "===> Database name determined to be %s" % db_name
  return db_name


# Get the database username of an existing Drupal website
@task
@roles('app_primary')
def get_db_user(repo, branch, site, drush_output):
  db_user = None
  db_user = run("echo \"%s\" | grep \"db-username:\" | cut -d \":\" -f 2" % drush_output)

  # If the dbuser variable is empty for whatever reason, resort to grepping settings.php
  if not db_user:
    with cd("/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)):
      print "===> drush did not give us a database username so grepping the settings file"
      db_user = sudo("grep \"'username' => '%s*\" settings.php | cut -d \">\" -f 2" % repo)
      db_user = db_user.translate(None, "',")
  print "===> Database username determined to be %s" % db_user
  return db_user


# Generate a crontab for running drush cron on this site
@task
@roles('app_primary')
def generate_drush_cron(alias, branch, autoscale=None):
  if exists("/etc/cron.d/%s_%s_cron" % (alias, branch)):
    print "===> Cron already exists, moving along"
  else:
    if autoscale is None:
      print "===> No cron job, creating one now"
      now = datetime.datetime.now()
      sudo("touch /etc/cron.d/%s_%s_cron" % (alias, branch))
      append_string = """%s * * * *       www-data  /usr/local/bin/drush @%s_%s cron > /dev/null 2>&1""" % (now.minute, alias, branch)
      append("/etc/cron.d/%s_%s_cron" % (alias, branch), append_string, use_sudo=True)
      print "===> New Drupal cron job created at /etc/cron.d/%s_%s_cron" % (alias, branch)
    else:
      print "===> This is an autoscale layout, cron should be handled by another task runner such as Jenkins"


# This function is used to get a fresh database of the site to import into the custom
# branch site during the initial_build() step
@task
def prepare_database(repo, branch, build, buildtype, alias, site, syncbranch, orig_host, sanitise, sanitised_password, sanitised_email, freshinstall=True):
  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.read_config_file()
  now = common.Utils._gen_datetime()
  dump_file = None

  if syncbranch is None:
    raise SystemError("######## Sync branch cannot be empty when wanting a fresh database when deploying a custom branch for the first time. Aborting early.")

  current_env = env.host

  if not freshinstall:
    drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)
    drush_output = Drupal.drush_status(repo, branch, build, buildtype, site, drush_runtime_location)
    db_name = get_db_name(repo, branch, build, buildtype, site, drush_output)

  # If freshinstall is True, this occurs during an initial build, so we need to check if there's
  # a db/ directory, remove all .sql.bz2 files. If a db/ directory doesn't exist create one. If
  # this isn't a freshinstall, we don't need to do anything with the db/ directory
  with settings(warn_only=True):
    if freshinstall:
      if run("find /var/www/%s_%s_%s -maxdepth 1 -type d -name db | egrep '.*'" % (repo, branch, build)).return_code == 0:
        sudo("rm /var/www/%s_%s_%s/db/*.sql.bz2" % (repo, branch, build))
        print "===> Found a /db directory, so removed all .sql.bz2 files."
      else:
        run("mkdir -p /var/www/%s_%s_%s/db" % (repo, branch, build))
        print "===> Could not find a /db directory, so one was created."

  # Let's first get the hostname of the server where the site we want a fresh db from resides
  # Typically, the stage site had a buildtype of [stage], but the master/dev site has [dev]
  if config.has_section(syncbranch):
    sync_branch_host = config.get(syncbranch, repo)
  else:
    # We cannot find a section with that buildtype, so abort
    raise SystemError("######## Cannot find a buildtype %s in config.ini. Aborting." % syncbranch)

  # If sync_branch_host and current_env match, we don't need to connect to another
  # server to get the dump
  if sync_branch_host == current_env:
    # Check that the syncbranch site exists on this server
    syncbranch_site = common.Utils.get_previous_build(repo, syncbranch, None)
    if syncbranch_site is None:
      raise SystemError("######## Cannot find a site to sync the database from. Aborting.")

    # If freshinstall is True, this occurs during the initial build, so we create a new database
    # dump in the db/ directory which will be imported
    if freshinstall:
      print "===> Database to get a fresh dump from is on the same server. Getting database dump now..."
      # Time to dump the database and save it to db/
      dump_file = "%s_%s.sql.bz2" % (alias, syncbranch)
      run('cd /var/www/live.%s.%s/www/sites/%s && drush -l %s -y sql-dump --result-file=/dev/stdout --result-file=/dev/stdout | bzip2 -f > /var/www/%s_%s_%s/db/%s' % (repo, syncbranch, site, site, repo, branch, build, dump_file))
    else:
      # Because freshinstall is False and the site we're syncing from is on the same server,
      # we can use drush sql-sync to sync that database to this one
      print "===> Database to sync to site is on the same server. Syncing %s database now..." % syncbranch
      run("drush @%s_%s -y sql-drop" % (alias, branch))
      if run("drush sql-sync -y @%s_%s @%s_%s" % (alias, syncbranch, alias, branch)).failed:
        common.MySQL.mysql_revert_db(db_name, build)
        raise SystemError("######## Could not sync %s database. Reverting the %s database and aborting." % (syncbranch, branch))
      else:
        print "===> %s database synced successfully." % syncbranch

      # For cases where we processed the import, we do not want to send dump_file back
      dump_file = None

  # If sync_branch_host and current_env don't match, the database to fetch to on another server
  else:
    env.host = sync_branch_host
    env.user = "jenkins"
    env.host_string = '%s@%s' % (env.user, env.host)
    print "===> Switching host to %s to get database dump..." % env.host_string

    # Check that the syncbranch site exists on this server
    syncbranch_site = common.Utils.get_previous_build(repo, syncbranch, None)
    # Check the site exists on the host server. If not, abort
    if syncbranch_site is None:
      raise SystemError("######## Cannot find a site to sync the database from. Aborting.")

    if sanitise == "yes":
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/drupal-obfuscate.rb', '/home/jenkins', mode=0755).failed:
        raise SystemExit("######## Could not copy the obfuscate script to the application server, aborting as we cannot safely sanitise the live data")
      else:
        print "===> Obfuscate script copied to %s:/home/jenkins/drupal-obfuscate.rb - obfuscating data" % env.host
        with settings(hide('running', 'stdout', 'stderr')):
          drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, syncbranch, site)
          dbname_output = DrupalUtils.drush_command("status -l %s Database\ name" % site, drush_site=None, drush_runtime_location=drush_runtime_location, drush_sudo=False, drush_format=None, drush_path=None, www_user=False)
          dbuser_output = DrupalUtils.drush_command("status -l %s Database\ user" % site, drush_site=None, drush_runtime_location=drush_runtime_location, drush_sudo=False, drush_format=None, drush_path=None, www_user=False)
          dbpass_output = DrupalUtils.drush_command("--show-passwords status -l %s Database\ pass" % site, drush_site=None, drush_runtime_location=drush_runtime_location, drush_sudo=False, drush_format=None, drush_path=None, www_user=False)
          dbhost_output = DrupalUtils.drush_command("status -l %s Database\ host" % site, drush_site=None, drush_runtime_location=drush_runtime_location, drush_sudo=False, drush_format=None, drush_path=None, www_user=False)

          dbname = run("echo \"%s\" | awk {'print $4'} | head -1" % dbname_output)
          dbuser = run("echo \"%s\" | awk {'print $4'} | head -1" % dbuser_output)
          dbpass = run("echo \"%s\" | awk {'print $4'} | head -1" % dbpass_output)
          dbhost = run("echo \"%s\" | awk {'print $4'} | head -1" % dbhost_output)

          run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /home/jenkins/drupal-obfuscate.rb | bzip2 -f > ~jenkins/dbbackups/custombranch_%s_%s.sql.bz2' % (dbuser, dbpass, dbhost, dbname, alias, now))
    else:
      run('cd /var/www/live.%s.%s/www/sites/%s && drush -l %s -y sql-dump | bzip2 -f > ~jenkins/dbbackups/custombranch_%s_%s.sql.bz2' % (repo, syncbranch, site, site, alias, now))

    print "===> Fetching the database from the remote server..."
    dump_file = "custombranch_%s_%s_from_%s.sql.bz2" % (alias, now, syncbranch)
    get('~/dbbackups/custombranch_%s_%s.sql.bz2' % (alias, now), '/tmp/dbbackups/%s' % dump_file)
    run('rm ~/dbbackups/custombranch_%s_%s.sql.bz2' % (alias, now))

    # Switch back to original host and send the database dump to it
    env.host_string = orig_host
    print "===> Host string is now %s..." % env.host_string
    print "===> Sending database dump to host..."

    # If freshinstall is True, this is for an initial build, so we just need to copy the database
    # into the db/ directory and do nothing else with it. If freshinstall is False, this is to
    # sync the chosen database to the custom branch site, so we copy it to /home/jenkins/dbbackups
    # then import it
    if freshinstall:
      local('scp /tmp/dbbackups/%s %s:/var/www/%s_%s_%s/db/' % (dump_file, env.host_string, repo, branch, build))
    else:
      local('scp /tmp/dbbackups/%s %s:~/dbbackups/' % (dump_file, env.host_string))
      print "===> Importing the %s database into %s..." % (syncbranch, branch)
      # Need to drop all tables first in case there are existing tables that have to be ADDED
      # from an upgrade
      run("drush @%s_%s -y sql-drop" % (alias, branch))
      with settings(warn_only=True):
        if run("bzcat ~/dbbackups/%s | drush @%s_%s sql-cli" % (dump_file, alias, branch)).failed:
          common.MySQL.mysql_revert_db(db_name, build)
          raise SystemError("######## Cannot import %s database into %s. Reverting database and aborting." % (syncbranch, alias))
        else:
          if sanitise == "yes":
            if sanitised_password is None:
              sanitised_password = common.Utils._gen_passwd()
            if sanitised_email is None:
              sanitised_email = 'example.com'
            print "===> Sanitising database..."
            run("drush @%s_%s -y sql-sanitize --sanitize-email=%s+%%uid@%s --sanitize-password=%s" % (alias, branch, alias, sanitised_email, sanitised_password))
            print "===> Data sanitised, email domain set to %s+%%uid@%s, passwords set to %s" % (alias, sanitised_email, sanitised_password)
          print "===> %s database imported." % syncbranch

      # For cases where we processed the import, we do not want to send dump_file back
      dump_file = None

      # Tidying up on host server
      run("rm ~/dbbackups/%s" % dump_file)

    # Tidying up on Jenkins server
    local('rm /tmp/dbbackups/%s' % dump_file)

  # Send the dump_file back for later use
  return dump_file


# Run a drush status against that build
# Failures here should be reverting the database, because the site gets taken offline. If it fails to run drush st and the build fails, the site will remain offline! Probably need to revert the db nearly every time this function fails, as it is called after the site is taken offline. Only caveat *might* be when Drupal.prepare_database() is called during a feature branch build.
@task
@roles('app_primary')
def drush_status(repo, branch, build, buildtype, site, drush_runtime_location=None, alias=None, db_backup=True, revert=False, revert_settings=False, sites_deployed=None):
  print "===> Running a drush status test"
  if not drush_runtime_location:
    drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  drush_output = DrupalUtils.drush_command("status", site, drush_runtime_location, False, "yaml")
  if run("echo \"%s\" | egrep 'Connected|Successful'" % drush_output).failed:
    print "###### Could not bootstrap the database!"
    if revert == False and revert_settings == True:
      for revert_alias,revert_site in sites_deployed.iteritems():
        execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
        execute(Revert._revert_go_online, repo, branch, build, buildtype, site)
    else:
      if revert:
        for revert_alias,revert_site in sites_deployed.iteritems():
          if db_backup:
            execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
          else:
            print "####### Due to your config settings no database backup was taken so your database may be broken!"
          execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
    raise SystemExit("###### Could not bootstrap the database on this build! Aborting")
  else:
    # Send back the drush output in case we need it
    return drush_output


# Run drush updatedb to apply any database changes from hook_update's
@task
@roles('app_primary')
def drush_updatedb(repo, branch, build, buildtype, site, alias, drupal_version, db_backup, sites_deployed=None):
  print "===> Running any database hook updates"
  with settings(warn_only=True):
    # Clear the Drupal cache before running database updates, as sometimes there can be unexpected results
    drush_clear_cache(repo, branch, build, site, drupal_version)
    # Apparently APC cache can interfere with drush updatedb expected results here. Clear any chance of caches
    common.Services.clear_php_cache()
    common.Services.clear_varnish_cache()
    # Set drush location
    drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
    if DrupalUtils.drush_command("updatedb", site, drush_runtime_location, True, None, None, True).failed:
      print "###### Could not apply database updates! Reverting this database"
      for revert_alias,revert_site in sites_deployed.iteritems():
        if db_backup:
          execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
        else:
          print "####### Due to your config settings no database backup was taken so your database may be broken!"
        execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
      raise SystemExit("###### Could not apply database updates! Reverted database. Site remains on previous build")
    if drupal_version > 7:
      if DrupalUtils.drush_command("entity-updates", site, drush_runtime_location, True, None, None, True).failed:
        print "###### Could not carry out entity updates! Continuing anyway, as this probably isn't a major issue."
  print "===> Database updates applied"
  drush_clear_cache(repo, branch, build, site, drupal_version)


# Function to revert all features using --force
@task
@roles('app_primary')
def drush_fra(repo, branch, build, buildtype, site, alias, drupal_version, sites_deployed=None):
  # Set drush variables
  drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  if run("cd %s && drush -y --format=yaml -l %s pm-list --pipe --type=module --status=enabled --no-core | grep -q ^features:$" % (drush_runtime_location, site)).return_code != 0:
    print "===> Features module not installed, skipping feature revert"
  else:
    print "===> Reverting all features..."
    with settings(warn_only=True):
      if DrupalUtils.drush_command("fra", site, drush_runtime_location, True, None, None, True).failed:
        print "###### Could not revert features! Reverting database and settings..."
        for revert_alias,revert_site in sites_deployed.iteritems():
          execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
          execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
        raise SystemExit("###### Could not revert features! Site remains on previous build")
      else:
        drush_clear_cache(repo, branch, build, site, drupal_version)


# Function to run Drupal cron (mainly used by RBKC's microsites that use the Domain module)
@task
@roles('app_primary')
def drush_cron(repo, branch, build, site, drupal_version):
  print "===> Running Drupal cron..."
  drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  with settings(warn_only=True):
    if DrupalUtils.drush_command("cron", site, drush_runtime_location).failed:
      print "###### Could not run cron!"
      raise SystemExit("###### Could not run cron! Site remains on previous build.")
    else:
      drush_clear_cache(repo, branch, build, site, drupal_version)


# Function that can be used to clear Drupal cache
@task
@roles('app_primary')
def drush_clear_cache(repo, branch, build, site, drupal_version):
  print "===> Clearing Drupal cache..."
  with settings(warn_only=True):
    if drupal_version > 7:
      drush_command = "cr"
    else:
      drush_command = "cc all"

    drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
    DrupalUtils.drush_command(drush_command, site, drush_runtime_location, True, None, None, True)


# Manage or setup the 'environment_indicator' Drupal module, if it exists in the build
# See RS11494
@task
@roles('app_primary')
def environment_indicator(www_root, repo, branch, build, buildtype, alias, site, drupal_version):
  # Check if the module exists in the build
  with settings(warn_only=True):
    if run("find %s/%s_%s_%s/www -type d -name environment_indicator | egrep '.*'" % (www_root, repo, branch, build)).return_code == 0:
      environment_indicator_module = True
      print "===> environment_indicator module exists"
    else:
      environment_indicator_module = False
      print "===> environment_indicator module does not exist"

  # The module exists, now check if it's configured
  if environment_indicator_module:
    # Set up colours
    if buildtype == "dev":
      environment_indicator_color = "#00E500"
    elif buildtype == "stage":
      environment_indicator_color = "#ff9b01"
    else:
      # We don't know this buildtype, let's assume the worst and treat it as prod
      environment_indicator_color = "#ff0101"

    # Append the config to settings.inc if not already present
    # Use of Fabfile's 'append()' is meant to silently ignore if the text already exists in the file. So we don't bother
    # checking for it - if it exists but with a different value, appending will overrule the previous entry (maybe a bit
    # ugly or confusing when reading the file, but saves a horrible amount of kludge here grepping for existing entries)
    if drupal_version == 7:

      # Unfortunately this can't check inside the $buildtype.settings.php include, if there is one, so we still need to
      # check for that.
      print "===> Drupal 7 site, checking in %s/%s_%s_%s/www/sites/%s/%s.settings.php for $conf['environment_indicator_overwritten_name']" % (www_root, repo, branch, build, site, buildtype)
      contain_string = "$conf['environment_indicator_overwritten_name']"
      settings_file = "%s/%s_%s_%s/www/sites/%s/%s.settings.php" % (www_root, repo, branch, build, site, buildtype)
      does_contain = contains(settings_file, contain_string, exact=False, use_sudo=True)

      if does_contain:
        print "===> Settings already exist in %s.settings.php, we will not write anything to %s/config/%s_%s.settings.inc" % (buildtype, www_root, alias, branch)

      else:
        print "===> Checking for and appending environment_indicator settings to %s/config/%s_%s.settings.inc" % (www_root, alias, branch)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$conf['environment_indicator_overwrite'] = 'TRUE';", True)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$conf['environment_indicator_overwritten_name'] = '%s';" % buildtype, True)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$conf['environment_indicator_overwritten_color'] = '%s';" % environment_indicator_color, True)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$conf['environment_indicator_overwritten_text_color'] = '#ffffff';", True)

    if drupal_version > 7:

      # Unfortunately this can't check inside the $buildtype.settings.php include, if there is one, so we still need to
      # check for that.
      print "===> Drupal 8+ site, checking in %s/%s_%s_%s/www/sites/%s/%s.settings.php for $config['environment_indicator.indicator']['name']" % (www_root, repo, branch, build, site, buildtype)
      contain_string = "$config['environment_indicator.indicator']['name']"
      settings_file = "%s/%s_%s_%s/www/sites/%s/%s.settings.php" % (www_root, repo, branch, build, site, buildtype)
      does_contain = contains(settings_file, contain_string, exact=False, use_sudo=True)

      if does_contain:
        print "===> Settings already exist in %s.settings.php, we will not write anything to %s/config/%s_%s.settings.inc" % (buildtype, www_root, alias, branch)

      else:
        print "===> Checking for and appending environment_indicator settings to %s/config/%s_%s.settings.inc" % (www_root, alias, branch)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$config['environment_indicator.indicator']['name'] = '%s';" % buildtype, True)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$config['environment_indicator.indicator']['bg_color'] = '%s';" % environment_indicator_color, True)
        append("%s/config/%s_%s.settings.inc" % (www_root, alias, branch), "$config['environment_indicator.indicator']['fg_color'] = '#ffffff';", True)

    if drupal_version > 6:
      drush_runtime_location = "%s/%s_%s_%s/www/sites/%s" % (www_root, repo, branch, build, site)
      DrupalUtils.drush_command("pm-enable environment_indicator", site, drush_runtime_location, True, None, None, True)
    if drupal_version == 6:
      print "Drupal 6 site. Not setting up environment_indicator at this time.."
  else:
    print "The environment_indicator module was not present. Moving on..."


# Function used by Drupal 8 builds to import site config
@task
@roles('app_primary')
def config_import(repo, branch, build, buildtype, site, alias, drupal_version, import_config_method, cimy_mapping, previous_build, sites_deployed=None):
  with settings(warn_only=True):
    # Check to see if this is a Drupal 8 build
    if drupal_version > 7:
      import_config_command = DrupalConfig.import_config_command(repo, branch, build, site, import_config_method, cimy_mapping)

      print "===> Importing configuration for Drupal 8 site..."
      drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
      if DrupalUtils.drush_command("%s" % import_config_command, site, drush_runtime_location, True, None, None, True).failed:
        print "###### Could not import configuration! Reverting this database and settings"
        for revert_alias,revert_site in sites_deployed.iteritems():
          execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
          execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
        raise SystemExit("###### Could not import configuration! Reverted database and settings. Site remains on previous build")
      else:
        print "===> Configuration imported. Running a cache rebuild..."
        drush_clear_cache(repo, branch, build, site, drupal_version)


# Function to export site config
@task
@roles('app_primary')
def config_export(repo, branch, build, drupal_version):
  if drupal_version > 7:
    print "===> Executing hook: config_export"
    print "===> Exporting site config, which will be downloadable"
    with settings(warn_only=True):
      print "First see if the directory /var/www/shared/%s_%s_exported_config exists." % (repo, branch)
      if run("stat /var/www/shared/%s_%s_exported_config" % (repo, branch)).return_code == 0:
        print "Exported config directory exists. Remove its contents"
        if sudo("rm -r /var/www/shared/%s_%s_exported_config" % (repo, branch)).failed:
          print "Warning: Cannot remove old exported config. Stop exporting, but proceed with rest of the build"
        else:
          print "Exporting config"
          sudo("chown -R jenkins:www-data /var/www/shared/%s_%s_exported_config" % (repo, branch))
          # Set drush variables
          drush_runtime_location = "%s/%s_%s_%s/www/sites/%s" % (www_root, repo, branch, build, site)
          drush_command = "cex --destination=/var/www/shared/%s_%s_exported_config" % (repo, branch)
          if DrupalUtils.drush_command(drush_command, site, drush_runtime_location, True, None, None, True).failed:
            print "###### Warning: Cannot export config. Stop exporting, but proceed with rest of the build"
          else:
            print "===> Exported config successfully. It will be available at /var/www/shared/%s_%s_exported_config" % (repo, branch)


# Take the site offline (prior to drush updatedb)
@task
@roles('app_primary')
def go_offline(repo, branch, site, alias, readonlymode, drupal_version):
  # readonlymode can either be 'maintenance' (the default) or 'readonlymode'
  # which uses the readonlymode module
  print "===> go_offline mode is %s" % readonlymode
  # Set drush location
  drush_runtime_location = "/var/www/live.%s.%s/www/sites/%s" % (repo, branch, site)
  # If readonlymode is 'readonlymode', check that it exists
  if readonlymode == "readonlymode":
    print "===> First checking that the readonlymode module exists..."
    with settings(warn_only=True):
      if run("find /var/www/live.%s.%s/www -type d -name readonlymode | egrep '.*'" % (repo, branch)).return_code == 0:
        print "===> It does exist, so enable it if it's not already enabled"
        # Enable the module if it isn't already enabled
        DrupalUtils.drush_command("pm-enable readonlymode", site, drush_runtime_location)
        # Set the site_readonly mode variable to 1
        print "===> Setting readonlymode so content cannot be changed while database updates are run..."
        DrupalUtils.drush_command("vset site_readonly 1", site, drush_runtime_location)
      else:
        print "###### The readonly flag in config.ini was set to readonly, yet the readonlymode module does not exist. We'll revert to normal maintenance mode..."
        readonlymode = 'maintenance'

  if readonlymode == "maintenance":
    print "===> Taking the site offline temporarily to do the drush updatedb..."
    if drupal_version > 7:
      DrupalUtils.drush_command("state-set system.maintenance_mode 1", site, drush_runtime_location)
    else:
      DrupalUtils.drush_command("vset site_offline 1", site, drush_runtime_location)
      DrupalUtils.drush_command("vset maintenance_mode 1", site, drush_runtime_location)


# Take the site online (after drush updatedb)
@task
@roles('app_primary')
def go_online(repo, branch, build, buildtype, alias, site, previous_build, readonlymode, drupal_version, sites_deployed=None):
  drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  # readonlymode can either be 'maintenance' (the default) or 'readonlymode', which uses the readonlymode module
  # If readonlymode is 'readonlymode', check that it exists
  if readonlymode == "readonlymode":
    print "===> First checking that the readonlymode module exists..."
    with settings(warn_only=True):
      if run("find /var/www/%s_%s_%s/www -type d -name readonlymode | egrep '.*'" % (repo, branch, build)).return_code == 0:
        print "It does exist, so enable it if it's not already enabled"
        # Enable the module if it isn't already enabled
        DrupalUtils.drush_command("pm-enable readonlymode", site, drush_runtime_location)
        # Set the site_readonly mode variable to 1
        print "===> Setting readonlymode back to 0 so content can once again be edited..."
        if DrupalUtils.drush_command("vset site_readonly 0", site, drush_runtime_location).failed:
          print "###### Could not set the site out of read only mode! Reverting this build and database."
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          for revert_alias,revert_site in sites_deployed.iteritems():
            execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
            execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
          raise SystemExit("###### Could not bring the sites back online! Reverted database and settings and repointed live symlink to previous build.")
      else:
        print "###### The readonly flag in config.ini was set to readonly, yet the readonlymode module does not exist. We'll revert to normal maintenance mode..."
        readonlymode = 'maintenance'

  if readonlymode == "maintenance":
    print "===> Taking the site back online..."
    with settings(warn_only=True):
      if drupal_version > 7:
        if DrupalUtils.drush_command("state-set system.maintenance_mode 0", site, drush_runtime_location).failed:
          print "###### Could not set the site back online! Reverting this build and database"
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          for revert_alias,revert_site in sites_deployed.iteritems():
            execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
            execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
          raise SystemExit("###### Could not bring the sites back online! Reverted database and settings and repointed live symlink to previous build.")
      else:
        if DrupalUtils.drush_command("vset site_offline 0", site, drush_runtime_location).failed:
          print "###### Could not set the site back online! Reverting this build and database"
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          for revert_alias,revert_site in sites_deployed.iteritems():
            execute(Revert._revert_db, repo, branch, build, buildtype, revert_site)
            execute(Revert._revert_settings, repo, branch, build, buildtype, revert_site, revert_alias)
          raise SystemExit("###### Could not bring the sites back online! Reverted database and settings and repointed live symlink to previous build.")
        else:
          DrupalUtils.drush_command("vset maintenance_mode 0", site, drush_runtime_location)

  print "Clear the cache after bringing the %s site back online." % site
  with settings(warn_only=True):
    drush_clear_cache(repo, branch, build, site, drupal_version)


# Set the username and password of user 1 to something random if the buildtype is 'prod'
@task
@roles('app_primary')
def secure_admin_password(repo, branch, build, site, drupal_version):
  print "===> Setting secure username and password for uid 1"
  drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  u1pass = common.Utils._gen_passwd(20)
  u1name = "codeenigma-%s-admin" % branch
  with cd('/var/www/%s_%s_%s/www/sites/%s' % (repo, branch, build, site)):
    with settings(warn_only=True):
      if drupal_version > 7:
        drush_command = 'sqlq "UPDATE users_field_data SET name = \'%s\' WHERE uid = 1"' % u1name
        DrupalUtils.drush_command(drush_command, site, drush_runtime_location)
      else:
        drush_command = 'sqlq "UPDATE users SET name = \'%s\' WHERE uid = 1"' % u1name
        DrupalUtils.drush_command(drush_command, site, drush_runtime_location)
      drush_clear_cache(repo, branch, build, site, drupal_version)
      drush_command = DrupalUtils.get_drush_user_password_command(u1name, u1pass)
      DrupalUtils.drush_command(drush_command, site, drush_runtime_location)


# Check if node access table will get rebuilt and warn if necessary
@task
def check_node_access(repo, alias, branch, build, site, notifications_email):
  drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
  with settings(warn_only=True):
    node_access_needs_rebuild = DrupalUtils.drush_command("php-eval 'echo node_access_needs_rebuild();'", site, drush_runtime_location)
    if node_access_needs_rebuild == 1:
      print "####### WARNING: this release needs the content access table to be rebuilt. This is an intrusive operation that imply the site needs to stay in maintenance mode untill the whole process is finished."
      print "####### Depending on the number of nodes and the complexity of access rules, this can take several hours. Be sure to either plan the release appropriately, or when possible use alternative method that are not intrusive."
      print "####### We recommend you consider this module: https://www.drupal.org/project/node_access_rebuild_progressive"
      # Send an email if an address is provided in config.ini
      if notifications_email:
        local("echo 'Your build for %s of branch %s has triggered a warning of a possible content access table rebuild - this may cause an extended outage of your website. Please review!' | mail -s 'Content access table warning' %s" % (alias, branch, notifications_email))
        print "===> Sent warning email to %s" % notifications_email
    else:
      print "===> Node access rebuild check completed, as far as we can tell this build is safe"
