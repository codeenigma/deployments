from fabric.api import *
from fabric.contrib.files import *
import random
import string
import common.ConfigFile
import common.Services
import common.Utils
import Revert


@task
def drush_fra_branches(config, branch):
  # If a 'branches' option exists in the [Features] section in config.ini, proceed
  if config.has_option("Features", "branches"):
    branches = []
    # Get the 'branches' option from under the [Features] section
    revert_features = config.get("Features", "branches")
    if revert_features == "*":
      #just append the current branch
      branches.append(branch)
    else:
      # Split the 'branches' option using a comma as a delimeter
      revert_features = revert_features.split(',')
      # For each value, strip it and add it to the branches list, which will be searched later
      for each_branch in revert_features:
        each_branch = each_branch.strip()
        branches.append(each_branch)
  # If a 'branches' option does not exist in the [Features] section, add master and stage
  # to the branches list. This is prevent any current jobs using the previous version of
  # this function to break
  else:
    branches = ['master', 'stage']
  return branches


# Set the default maintenance/readonly method
@task
def configure_readonlymode(config):
  # If config.ini has a [Readonly] section, proceed option
  if config.has_section("Readonly"):
    # Check that the [Readonly] section has a readonly option
    if config.has_option("Readonly", "readonly"):
      # Get the value of readonly in config.ini
      return config.get("Readonly", "readonly")


# Config the config_export hook
def configure_config_export(config):
  if config.has_section("Hooks"):
    if config.has_option("Hooks", "config_export"):
      return config.getboolean("Hooks", "config_export")


# Take a database backup
@task
@roles('app_primary')
def backup_db(alias, branch, build):
  print "===> Ensuring backup directory exists"
  with settings(warn_only=True):
    if run("mkdir -p ~jenkins/dbbackups").failed:
      raise SystemExit("Could not create directory ~jenkins/dbbackups! Aborting early")
  print "===> Taking a database backup..."
  with settings(warn_only=True):
    if run("drush @%s_%s sql-dump --skip-tables-key=common | gzip > ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz; if [ ${PIPESTATUS[0]} -ne 0 ]; then exit 1; else exit 0; fi" % (alias, branch, alias, branch, build)).failed:
      failed_backup = True
    else:
      failed_backup = False

  if failed_backup:
    raise SystemExit("Could not take database backup prior to launching new build! Aborting early")


# Generate a crontab for running drush cron on this site
@task
@roles('app_all')
def generate_drush_cron(repo, branch):
  print "===> Generating Drush cron for this site if it isn't there already"
  script_dir = os.path.dirname(os.path.realpath(__file__))
  if put(script_dir + '/../util/drush_cron', '/home/jenkins', mode=0755).failed:
    print "===> Could not copy the drush_cron script to the application server, cron will not be generated for this site"
  else:
    print "===> drush_cron copied to %s:/home/jenkins/drush_cron, making cron now" % env.host
    sudo("/home/jenkins/drush_cron %s %s" % (repo, branch))


# This function is used to get a fresh database of the site to import into the custom
# branch site during the initial_build() step
@task
def prepare_database(repo, branch, build, alias, syncbranch, orig_host, sanitise, drupal_version, sanitised_password, sanitised_email, freshinstall=True):
  # Read the config.ini file from repo, if it exists
  config = common.ConfigFile.read_config_file()
  now = common.Utils._gen_datetime()
  dump_file = None

  if syncbranch is None:
    raise SystemError("######## Sync branch cannot be empty when wanting a fresh database when deploying a custom branch for the first time. Aborting early.")

  current_env = env.host

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
    # Check a site exists on this server
    if run('drush sa | grep \'^@\?%s_%s$\' > /dev/null' % (alias, syncbranch)).failed:
      raise SystemError("######## Cannot find a site with the alias %s_%s. Aborting." % (alias, syncbranch))

    # If freshinstall is True, this occurs during the initial build, so we create a new database
    # dump in the db/ directory which will be imported
    if freshinstall:
      print "===> Database to get a fresh dump from is on the same server. Getting database dump now..."
      # Time to dump the database and save it to db/
      dump_file = "%s_%s.sql.bz2" % (alias, syncbranch)
      run('drush @%s_%s sql-dump | bzip2 -f > /var/www/%s_%s_%s/db/%s' % (alias, syncbranch, repo, branch, build, dump_file))
    else:
      # Because freshinstall is False and the site we're syncing from is on the same server,
      # we can use drush sql-sync to sync that database to this one
      print "===> Database to sync to site is on the same server. Syncing %s database now..." % syncbranch
      run("drush @%s_%s -y sql-drop" % (alias, branch))
      if run("drush sql-sync -y @%s_%s @%s_%s" % (alias, syncbranch, alias, branch)).failed:
        Revert._revert_db(alias, branch, build)
        raise SystemError("######## Could not sync %s database. Reverting the %s database and aborting." % (syncbranch, branch))
      else:
        print "===> %s database synced successfully." % syncbranch

  # If sync_branch_host and current_env don't match, the database to fetch to on another server
  else:
    env.host = sync_branch_host
    env.user = "jenkins"
    env.host_string = '%s@%s' % (env.user, env.host)
    print "===> Switching host to %s to get database dump..." % env.host_string

    # Check the site exists on the host server. If not, abort
    if run('drush sa | grep \'^@\?%s_%s$\' > /dev/null' % (alias, syncbranch)).failed:
      raise SystemError("######## Cannot find a site with the alias %s_%s. Aborting." % (alias, syncbranch))

    if sanitise == "yes":
      script_dir = os.path.dirname(os.path.realpath(__file__))
      if put(script_dir + '/../util/drupal-obfuscate.rb', '/home/jenkins', mode=0755).failed:
        raise SystemExit("######## Could not copy the obfuscate script to the application server, aborting as we cannot safely sanitise the live data")
      else:
        print "===> Obfuscate script copied to %s:/home/jenkins/drupal-obfuscate.rb - obfuscating data" % env.host
        with settings(hide('running', 'stdout', 'stderr')):
          dbname = run("drush @%s_%s status  Database\ name | awk {'print $4'} | head -1" % (alias, syncbranch))
          dbuser = run("drush @%s_%s status  Database\ user | awk {'print $4'} | head -1" % (alias, syncbranch))
          dbpass = run("drush @%s_%s --show-passwords status  Database\ pass | awk {'print $4'} | head -1" % (alias, syncbranch))
          dbhost = run("drush @%s_%s status  Database\ host | awk {'print $4'} | head -1" % (alias, syncbranch))
          run('mysqldump --single-transaction -c --opt -Q --hex-blob -u%s -p%s -h%s %s | /home/jenkins/drupal-obfuscate.rb | bzip2 -f > ~jenkins/dbbackups/custombranch_%s_%s.sql.bz2' % (dbuser, dbpass, dbhost, dbname, alias, now))
    else:
      run('drush @%s_%s sql-dump | bzip2 -f > ~jenkins/dbbackups/custombranch_%s_%s.sql.bz2' % (alias, syncbranch, alias, now))

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
          Revert._revert_db(alias, branch, build)
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

      # Tidying up on host server
      run("rm ~/dbbackups/%s" % dump_file)

    # Tidying up on Jenkins server
    local('rm /tmp/dbbackups/%s' % dump_file)

    # For cases where we processed the import, we do not want to send dump_file back
    dump_file = None

  # Send the dump_file back for later use
  return dump_file


# Function to install composer
@task
@roles('app_all')
def run_composer_install(repo, branch, build, composer_lock, no_dev):
  print "===> Running composer install on newly cloned codebase"

  # Apparently sometimes people keep Drupal 8's composer.json file in repo root.
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s/composer.json" % (repo, branch, build)).return_code == 0:
      path = "/var/www/%s_%s_%s" % (repo, branch, build)
    else:
      path = "/var/www/%s_%s_%s/www" % (repo, branch, build)

    print "path is %s" % path

  # Sometimes we will want to remove composer.lock prior to installing
  with settings(warn_only=True):
    print "===> Removing composer.lock prior to attempting an install"
    if composer_lock == False:
      run ("rm %s/composer.lock" % path)
      run ("rm -R %s/vendor" % path)

  if no_dev:
    run("cd %s && composer install --no-dev" % (path))
  else:
    run("cd %s && composer install --dev" % (path))


# Run a drush status against that build
@task
@roles('app_primary')
def drush_status(repo, branch, build, site, alias, revert=False, revert_settings=False):
  print "===> Running a drush status test"
  with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)):
    with settings(warn_only=True):
      if run("drush status | egrep 'Connected|Successful'").failed:
        print "Could not bootstrap the database!"
        if revert == False and revert_settings == True:
          Revert._revert_settings(repo, branch, build, site, alias)
        else:
          if revert == True:
            print "Reverting the database..."
            Revert._revert_db(alias, branch, build)
            Revert._revert_settings(repo, branch, build, site, alias)
        raise SystemExit("Could not bootstrap the database on this build! Aborting")

      if run("drush status").failed:
        if revert == False and revert_settings == True:
          Revert._revert_settings(repo, branch, build, site, alias)
        else:
          if revert == True:
            print "Reverting the database..."
            Revert._revert_db(alias, branch, build)
            Revert._revert_settings(repo, branch, build, site, alias)
        raise SystemExit("Could not bootstrap the database on this build! Aborting")


# Run drush updatedb to apply any database changes from hook_update's
@task
@roles('app_primary')
def drush_updatedb(repo, branch, build, site, alias, drupal_version):
  print "===> Running any database hook updates"
  with settings(warn_only=True):
    # Apparently APC cache can interfere with drush updatedb expected results here. Clear any chance of caches
    common.Services.clear_php_cache()
    common.Services.clear_varnish_cache()
    if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y updatedb'" % (repo, branch, build, site)).failed:
      print "Could not apply database updates! Reverting this database"
      Revert._revert_db(alias, branch, build)
      Revert._revert_settings(repo, branch, build, site, alias)
      raise SystemExit("Could not apply database updates! Reverted database. Site remains on previous build")
    if drupal_version == '8':
      if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y entity-updates'" % (repo, branch, build, site)).failed:
        print "Could not carry out entity updates! Continuing anyway, as this probably isn't a major issue."
  print "===> Database updates applied"
  drush_clear_cache(repo, branch, build, site, drupal_version)


# Function to revert all features using --force
@task
@roles('app_primary')
def drush_fra(repo, branch, build, site, alias, drupal_version):
  with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)):
    if run("drush pm-list --pipe --type=module --status=enabled --no-core | grep -q ^features$"):
      print "===> Features module not installed, skipping feature revert"
    else:
      print "===> Reverting all features..."
      with settings(warn_only=True):
        if sudo("su -s /bin/bash www-data -c 'drush -y fra'").failed:
          print "Could not revert features! Reverting database and settings..."
          Revert._revert_db(alias, branch, build)
          Revert._revert_settings(repo, branch, build, site, alias)
          raise SystemExit("Could not revert features! Site remains on previous build")
        else:
          drush_clear_cache(repo, branch, build, site, drupal_version)


# Function to run Drupal cron (mainly used by RBKC's microsites that use the Domain module)
@task
@roles('app_primary')
def drush_cron(repo, branch, build, site, drupal_version):
  print "===> Running Drupal cron..."
  with settings(warn_only=True):
    with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)):
      if sudo("drush -y cron").failed:
        print "Could not run cron!"
        raise SystemExit("Could not run cron! Site remains on previous build.")
      else:
        drush_clear_cache(repo, branch, build, site, drupal_version)


# Function that can be used to clear Drupal cache
@task
@roles('app_primary')
def drush_clear_cache(repo, branch, build, site, drupal_version):
  print "===> Clearing Drupal cache..."
  with settings(warn_only=True):
    if drupal_version == '8':
      sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y cr'" % (repo, branch, build, site))
    else:
      sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y cc all'" % (repo, branch, build, site))


# Manage or setup the 'environment_indicator' Drupal module, if it exists in the build
# See RS11494
@task
@roles('app_primary')
def environment_indicator(repo, branch, build, buildtype, alias, site, drupal_version):
  # Check if the module exists in the build
  with settings(warn_only=True):
    if run("find /var/www/%s_%s_%s/www -type d -name environment_indicator | egrep '.*'" % (repo, branch, build)).return_code == 0:
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
    if drupal_version == '7':

      # Unfortunately this can't check inside the $buildtype.settings.php include, if there is one, so we still need to
      # check for that.
      print "===> Drupal 7 site, checking in /var/www/%s_%s_%s/www/sites/%s/%s.settings.php for $conf['environment_indicator_overwritten_name']" % (repo, branch, build, site, buildtype)
      contain_string = "$conf['environment_indicator_overwritten_name']"
      settings_file = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
      does_contain = contains(settings_file, contain_string, exact=False, use_sudo=True)

      if does_contain:
        print "===> Settings already exist in %s.settings.php, we will not write anything to /var/www/config/%s_%s.settings.inc" % (buildtype, alias, branch)

      else:
        print "===> Checking for and appending environment_indicator settings to /var/www/config/%s_%s.settings.inc" % (alias, branch)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$conf['environment_indicator_overwrite'] = 'TRUE';", True)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$conf['environment_indicator_overwritten_name'] = '%s';" % buildtype, True)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$conf['environment_indicator_overwritten_color'] = '%s';" % environment_indicator_color, True)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$conf['environment_indicator_overwritten_text_color'] = '#ffffff';", True)

    if drupal_version == '8':

      # Unfortunately this can't check inside the $buildtype.settings.php include, if there is one, so we still need to
      # check for that.
      print "===> Drupal 8 site, checking in /var/www/%s_%s_%s/www/sites/%s/%s.settings.php for $config['environment_indicator.indicator']['name']" % (repo, branch, build, site, buildtype)
      contain_string = "$config['environment_indicator.indicator']['name']"
      settings_file = "/var/www/%s_%s_%s/www/sites/%s/%s.settings.php" % (repo, branch, build, site, buildtype)
      does_contain = contains(settings_file, contain_string, exact=False, use_sudo=True)

      if does_contain:
        print "===> Settings already exist in %s.settings.php, we will not write anything to /var/www/config/%s_%s.settings.inc" % (buildtype, alias, branch)

      else:
        print "===> Checking for and appending environment_indicator settings to /var/www/config/%s_%s.settings.inc" % (alias, branch)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$config['environment_indicator.indicator']['name'] = '%s';" % buildtype, True)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$config['environment_indicator.indicator']['bg_color'] = '%s';" % environment_indicator_color, True)
        append("/var/www/config/%s_%s.settings.inc" % (alias, branch), "$config['environment_indicator.indicator']['fg_color'] = '#ffffff';", True)

    if drupal_version == '7' or drupal_version == '8':
      sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y en environment_indicator'" % (repo, branch, build, site))
    if drupal_version == '6':
      print "Drupal 6 site. Not setting up environment_indicator at this time.."
  else:
    print "The environment_indicator module was not present. Moving on..."


# Function used by Drupal 8 builds to import site config
@task
@roles('app_primary')
def config_import(repo, branch, build, site, alias, drupal_version, previous_build):
  with settings(warn_only=True):
    # Check to see if this is a Drupal 8 build
    if drupal_version == '8':
      print "===> Importing configuration for Drupal 8 site..."
      if sudo("su -s /bin/bash www-data -c 'cd /var/www/%s_%s_%s/www/sites/%s && drush -y cim'" % (repo, branch, build, site)).failed:
        print "Could not import configuration! Reverting this database and settings"
        sudo("unlink /var/www/live.%s.%s" % (repo, branch))
        sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
        Revert._revert_db(alias, branch, build)
        Revert._revert_settings(repo, branch, build, site, alias)
        raise SystemExit("Could not import configuration! Reverted database and settings. Site remains on previous build")
      else:
        print "===> Configuration imported. Running a cache rebuild..."
        drush_clear_cache(repo, branch, build, site, drupal_version)


# Take the site offline (prior to drush updatedb)
@task
@roles('app_primary')
def go_offline(repo, branch, build, alias, readonlymode, drupal_version):
  # readonlymode can either be 'maintenance' (the default) or 'readonlymode', which uses the readonlymode module

  print "===> go_offline mode is %s" % readonlymode

  # If readonlymode is 'readonlymode', check that it exists
  if readonlymode == "readonlymode":
    print "===> First checking that the readonlymode module exists..."
    with settings(warn_only=True):
      if run("find /var/www/%s_%s_%s/www -type d -name readonlymode | egrep '.*'" % (repo, branch, build)).return_code == 0:
        print "It does exist, so enable it if it's not already enabled"
        # Enable the module if it isn't already enabled
        run("drush @%s_%s en -y readonlymode" % (alias, branch))
        # Set the site_readonly mode variable to 1
        print "===> Setting readonlymode so content cannot be changed while database updates are run..."
        run("drush @%s_%s -y vset site_readonly 1" % (alias, branch))
      else:
        print "Hm, the readonly flag in config.ini was set to readonly, yet the readonlymode module does not exist. We'll revert to normal maintenance mode..."
        readonlymode = 'maintenance'

  if readonlymode == "maintenance":
    print "===> Taking the site offline temporarily to do the drush updatedb..."
    if drupal_version == '8':
      run("drush @%s_%s -y state-set system.maintenancemode 1" % (alias, branch))
    else:
      run("drush @%s_%s -y vset site_offline 1" % (alias, branch))
      run("drush @%s_%s -y vset maintenance_mode 1" % (alias, branch))


# Take the site online (after drush updatedb)
@task
@roles('app_primary')
def go_online(repo, branch, build, alias, previous_build, readonlymode, drupal_version):
  # readonlymode can either be 'maintenance' (the default) or 'readonlymode', which uses the readonlymode module

  # If readonlymode is 'readonlymode', check that it exists
  if readonlymode == "readonlymode":
    print "===> First checking that the readonlymode module exists..."
    with settings(warn_only=True):
      if run("find /var/www/%s_%s_%s/www -type d -name readonlymode | egrep '.*'" % (repo, branch, build)).return_code == 0:
        print "It does exist, so enable it if it's not already enabled"
        # Enable the module if it isn't already enabled
        run("drush @%s_%s en -y readonlymode" % (alias, branch))
        # Set the site_readonly mode variable to 1
        print "===> Setting readonlymode back to 0 so content can once again be edited..."
        if run("drush @%s_%s -y vset site_readonly 0" % (alias, branch)).failed:
          print "Could not set the site out of read only mode! Reverting this build and database."
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          Revert._revert_db(alias, branch, build)
          Revert._revert_settings(repo, branch, build, site, alias)
      else:
        print "Hm, the readonly flag in config.ini was set to readonly, yet the readonlymode module does not exist. We'll revert to normal maintenance mode..."
        readonlymode = 'maintenance'

  if readonlymode == "maintenance":
    print "===> Taking the site back online..."
    with settings(warn_only=True):
      if drupal_version == '8':
        if run("drush @%s_%s -y state-set system.maintenancemode 0" % (alias, branch)).failed:
          print "Could not set the site back online! Reverting this build and database"
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          Revert._revert_db(alias, branch, build)
          Revert._revert_settings(repo, branch, build, site, alias)
      else:
        if run("drush @%s_%s -y vset site_offline 0" % (alias, branch)).failed:
          print "Could not set the site back online! Reverting this build and database"
          sudo("unlink /var/www/live.%s.%s" % (repo, branch))
          sudo("ln -s %s /var/www/live.%s.%s" % (previous_build, repo, branch))
          Revert._revert_db(alias, branch, build)
          Revert._revert_settings(repo, branch, build, site, alias)

        else:
          run("drush @%s_%s -y vset maintenance_mode 0" % (alias, branch))


# Set the username and password of user 1 to something random if the buildtype is 'prod'
@task
@roles('app_primary')
def secure_admin_password(repo, branch, build, site, drupal_version):
  print "===> Setting secure username and password for uid 1"
  u1pass = common.Utils._gen_passwd(20)
  u1name = common.Utils._gen_passwd(20)
  with cd('/var/www/%s_%s_%s/www/sites/%s' % (repo, branch, build, site)):
    with settings(warn_only=True):
      if drupal_version == '8':
        run('drush sqlq "UPDATE users_field_data SET name = \'%s\' WHERE uid = 1"' % u1name)
      else:
        run('drush sqlq "UPDATE users SET name = \'%s\' WHERE uid = 1"' % u1name)
      run("drush upwd %s --password='%s'" % (u1name, u1pass))


# Check if node access table will get rebuilt and warn if necessary
@task
def check_node_access(alias, branch, notifications_email):
  with settings(warn_only=True):
    node_access_needs_rebuild = run("drush @%s_%s php-eval 'echo node_access_needs_rebuild();'" % (alias, branch))
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
