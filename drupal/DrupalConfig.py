from fabric.api import *
import DrupalUtils
import common.ConfigFile
import common.Utils

@task
def configure_cimy_params(config, site):
  cimy_mapping = {}

  cimy_source_default = "../config/sync"
  cimy_delete_default = "../drush/config-delete.yml"
  cimy_install_default = "../config_install/"

  cimy_mapping['source'] = common.ConfigFile.return_config_item(config, "Drupal", "%s_cimy_source" % site, "string", cimy_source_default)
  cimy_mapping['delete'] = common.ConfigFile.return_config_item(config, "Drupal", "%s_cimy_delete" % site, "string", cimy_delete_default)
  cimy_mapping['install'] = common.ConfigFile.return_config_item(config, "Drupal", "%s_cimy_install" % site, "string", cimy_install_default)

  print "Final cimy_mapping is: %s" % cimy_mapping

  return cimy_mapping


@task
def check_cmi_tools_exists(repo, branch, build, site):
  with settings(warn_only=True):
    drush_runtime_location = "/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)
    cmi_tools_exists_output = DrupalUtils.drush_command("pm-list", drush_site=None, drush_runtime_location=drush_runtime_location)

    if run("grep \"drush_cmi_tools\" %s" % cmi_tools_exists_output).return_code == 0:
      print "##### CMI Tools is installed, so we'll use it."
      return True
    else:
      print "##### CMI Tools is not installed, so we'll need to revert back to using the default config import tool."
      return False
