<?php
namespace CodeEnigma\Deployments\Robo\common;

use Robo\Task\BaseTask;
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;

class ConfigTasks extends BaseTask implements TaskInterface
{
  use TaskIO;
  public function __construct() {}
  public function run() {}

  public function returnConfigItem(
    $build_type,
    $section,
    $item,
    $default_value = null,
    $notify = true,
    $cast_value = false,
    $var_type = "string",
    $deprecate = false,
    $replacement_section = null
    ) {
      $value = \Robo\Robo::Config()->get("command.build.$build_type.$section.$item", $default_value);
      if ($value) {
        if ($deprecate) {
          if ($replacement_section) {
            $this->printTaskError("###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! Please use '$replacement_section' instead\n");
          }
          else {
            $this->printTaskError("###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! This option is being REMOVED!\n");
          }
        }
        if ($notify) {
          $this->printTaskSuccess("===> '$item' in '$section' being set to '$value'");
        }
        if ($cast_value) {
          settype($value, $var_type);
        }
      }
      return $value;
  }

  public function defineHost(
    $build_type
    ) {
      $host = \Robo\Robo::Config()->get('command.build.' . $build_type . '.server.host');
      if ($host) {
        $this->printTaskSuccess("===> Host is $host");
        $GLOBALS['host'] = $host;
      }
      else {
        $this->printTaskError("###### No host specified. Aborting!");
        exit("Aborting build!\n");
      }
  }

  public function defineRoles(
    $cluster,
    $build_type,
    $autoscale = null,
    $aws_credentials = null,
    $aws_autoscale_group = null
    ) {
      if ($cluster && $autoscale) {
        $this->printTaskError("###### You cannot be both a traditional cluster and an autoscale layout. Aborting!");
        exit("Aborting build!\n");
      }
      # Build roles for a traditional cluster
      if ($cluster) {
        $this->printTaskSuccess("===> This is a cluster, setting up cluster roles");
        # Reset the $cluster variable as an array of servers
        $cluster = \Robo\Robo::Config()->get('command.build.' . $build_type . '.server.cluster');
        $GLOBALS['roles'] = array(
          'app_all' => $cluster['app-servers'],
          'db_all' => $cluster['db-servers'],
          'app_primary' => array($cluster['app-servers'][0]),
          'db_primary' => array($cluster['db-servers'][0]),
          'cache_all' => $cluster['cache-servers'],
        );
        print_r($GLOBALS['roles']);
      }
      # Build roles for an AWS autoscale layout
      elseif ($autoscale) {

      }
      # Build roles for a single server
      else {
        $host = $GLOBALS['host'];
        $this->printTaskSuccess("===> Not a cluster, setting all roles to $host");
        $GLOBALS['roles'] = array(
          'app_all' => array($host),
          'db_all' => array($host),
          'app_primary' => array($host),
          'db_primary' => array($host),
          'cache_all' => array($host),
        );
      }
  }

}