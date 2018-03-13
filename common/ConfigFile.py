from fabric.api import *
import os
import sys
import string
import ConfigParser


# This task is a wrapper for read_config_file() to
# optionally allow a config file per buildtype
@task
def buildtype_config_file(buildtype, config_filename='config.ini', abort_if_missing=True, fullpath=False, remote=False):
  cwd = os.getcwd()
  buildtype_config_filename = buildtype + '.' + config_filename
  if os.path.isfile(cwd + '/' + buildtype_config_filename):
    config_filename = buildtype_config_filename
  print "===> Proceeding with config file %s" % config_filename
  return read_config_file(config_filename, abort_if_missing, fullpath, remote)


@task
def read_config_file(config_filename='config.ini', abort_if_missing=True, fullpath=False, remote=False):
  # Fetch the host to deploy to, from the mapfile, according to its repo and build type
  config_file = ConfigParser.RawConfigParser()
  # Force case-sensitivity
  config_file.optionxform = str
  cwd = os.getcwd()

  # Try and read a config.ini from the repo's root directory, if present
  if fullpath is False:
    path_to_config_file = cwd + '/' + config_filename
  else:
    path_to_config_file = config_filename
  if remote is False:
    print "===> Trying to read LOCAL file %s if it is present" % path_to_config_file
    if os.path.isfile(path_to_config_file):
      config_file.read(path_to_config_file)
      return config_file
    # Otherwise, abort the build / report missing file.
    else:
      if abort_if_missing is True:
        raise SystemError("===> We didn't find %s, aborting" % path_to_config_file)
      else:
        print "===> No config file found, but we will carry on regardless"
  else:
    print "===> Trying to read REMOTE file %s if it is present" % path_to_config_file
    if run("find %s -type f" % path_to_config_file).return_code == 0:
      config_file_contents = run("cat %s" % path_to_config_file)
      local_config_path = cwd + '/config.ini'
      local("echo '%s' > %s" % (config_file_contents, local_config_path))
      config_file.read(local_config_path)
      return config_file
    # Otherwise, abort the build / report missing file.
    else:
      if abort_if_missing is True:
        raise SystemError("===> We didn't find %s, aborting" % path_to_config_file)
      else:
        print "===> No config file found, but we will carry on regardless"


@task
def return_config_item(config, section, item, var_type="string", default_value=None, notify=True, deprecate=False, replacement_section=None):
  # Load in our config if it exists
  if config.has_option(section, item):
    # deprecate is a flag to say if this config option is obsolete and soon to be removed
    if deprecate:
      if replacement_section:
        print "############### Fetching %s from [%s] in config.ini - DEPRECATED! Please use [%s] instead" % (item, section, replacement_section)
      else:
        print "############### Fetching %s from [%s] in config.ini - DEPRECATED! This option is being removed!" % (item, section, replacement_section)
    # Now let's set the actual value from config
    if var_type is "string":
      if notify:
        print "===> %s in [%s] being set to %s" % (item, section, config.get(section, item))
      default_value = config.get(section, item)
    elif var_type is "boolean":
      if notify:
        print "===> %s in [%s] being set to %s" % (item, section, config.getboolean(section, item))
      default_value = config.getboolean(section, item)
    elif var_type is "int":
      if notify:
        print "===> %s in [%s] being set to %s" % (item, section, config.getint(section, item))
      default_value = config.getint(section, item)
    else:
      if notify:
        print "===> tried to look up %s %s in [%s] but type not found" % (var_type, item, section)
  # Either the default value remains unchanged, or we've modified it
  # In either case, let's send it back
  return default_value
