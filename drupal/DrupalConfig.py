from fabric.api import *
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
def import_config_command(repo, branch, build, site, import_config_method, cimy_mapping):
  if import_config_method == "cimy":
    if not check_cmi_tools_exists(repo, branch, build, site):
      import_config_method = "cim"

  if import_config_method == "cimy":
    return_command = "cimy --source=%s --delete-list=%s --install=%s" % (cimy_mapping['source'], cimy_mapping['delete'], cimy_mapping['install'])
  else:
    return_command = "cim"

  return return_command


@task
def check_cmi_tools_exists(repo, branch, build, site):
  with settings(warn_only=True):
    with cd("/var/www/%s_%s_%s/www/sites/%s" % (repo, branch, build, site)):

      if run("drush | grep \"drush_cmi_tools\"").return_code == 0:
        print "##### CMI Tools is installed, so we'll use it."
        return True
      else:
        print "##### CMI Tools is not installed, so we'll need to revert back to using the default config import tool."
        return False
