<?php
namespace CodeEnigma\Deployments\Robo\common;

use Robo\Task\BaseTask;
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;
use Aws\AutoScaling\AutoScalingClient;
use Aws\Ec2;


class ConfigTasks extends BaseTask implements TaskInterface
{
  use TaskIO;

  public function __construct() {}
  public function run() {}

  /**
   * Function for fetching config from the YAML file or returning a default value
   *
   * @param string $build_type
   * @param string $section Section of the config to load
   * @param string $item Name of the item to load
   * @param mixed $default_value Default value to be returned if nothing is found
   * @param boolean $notify Flag to notify in build output or not
   * @param boolean $cast_value Flag to say if we should try and cast variables
   * @param string $var_type Type of variable, must be a valid PHP cast - http://php.net/manual/en/language.types.type-juggling.php
   * @param boolean $deprecate Optional flag to warn if this is a deprecated config item
   * @param string $replacement_section Optional section to advise users to move this config item to
   * @return mixed Either the default value passed in or the value loaded from config
   */
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

  /**
   * Define the primary host for this build
   *
   * @param string $build_type
   * @param boolean $autoscale
   */
  public function defineHost(
    $build_type,
    $autoscale
    ) {
      if (!$autoscale) {
        $host = \Robo\Robo::Config()->get('command.build.' . $build_type . '.server.host');
        if ($host) {
          $this->printTaskSuccess("===> Host is $host");
          $GLOBALS['host'] = $host;
        }
        else {
          $this->printTaskError("###### No host specified. Aborting!");
          exit("Aborting build!\n");
        }
        # Optionally set a provided host IP address
        $host_ip = \Robo\Robo::Config()->get('command.build.' . $build_type . '.server.host-ip');
        if ($host_ip) {
          $this->printTaskSuccess("===> Host IP address is $host_ip");
          $GLOBALS['host_ip'] = $host_ip;
        }
      }
      else {
        $this->printTaskSuccess("===> We cannot get a host address for autoscale, it will be set when roles are defined");
      }
  }

  /**
   * Define the roles of the server(s) available
   *
   * @param boolean $cluster
   * @param string $build_type
   * @param boolean $autoscale
   * @param string $aws_credentials Location of the AWS credentials file
   * @param string $aws_autoscale_group Name of the autoscale group we are targetting
   */
  public function defineRoles(
    $cluster,
    $build_type,
    $autoscale = false,
    $aws_autoscale_group = ""
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
          'app_ips' => $cluster['app-ips'],
          'db_all' => $cluster['db-servers'],
          'db_ips' => $cluster['db-ips'],
          'app_primary' => array($cluster['app-servers'][0]),
          'db_primary' => array($cluster['db-servers'][0]),
          'cache_all' => $cluster['cache-servers'],
        );
      }
      # Build roles for an AWS autoscale layout
      elseif ($autoscale) {
        $aws = \Robo\Robo::Config()->get('command.build.' . $build_type . '.aws');
        if ($aws) {
          if ($aws['access-key-id'] && $aws['secret-access-key']) {
            $this->printTaskSuccess("===> Credentials provided by config");
            $aws_client_settings = array(
              'key' => $aws['access-key-id'],
              'secret' => $aws['secret-access-key'],
              'region'  => $aws['region']
            );
          }
          else {
            $this->printTaskSuccess("===> Credentials provided by AWS 'credentials' file");
            $aws_client_settings = array(
              'profile' => $aws['profile'],
              'region'  => $aws['region']
            );
          }
          # New AWS autoscaling client, assumes CI server/container has an AWS profile in a credentials file
          # in the home directory of the user executing these CI scripts
          $client = AutoScalingClient::factory($aws_client_settings);
          $result = $client->describeAutoScalingGroups();
          # Cycle through autoscale groups available for this account
          foreach ($result['AutoScalingGroups'] as $group) {
            # Find the matching group
            if ($group['AutoScalingGroupName'] == $aws['group-name']) {
              # Cycle through the instances in that group and grab the instance IDs
              foreach ($group['Instances'] as $instance) {
                $instance_ids[] = $instance['InstanceId'];
              }
            }
          }
          # Moving on, for each instance ID we got, use Ec2 to describe them and grab the private IP address
          $instance_client = Ec2::factory($aws_client_settings);
          foreach ($instance_ids as $instance_id) {
            $instance_data = $instance_client->describeInstances(['InstanceIds' => [$instance_id]]);
            $instance_ips[] = $instance_data['Reservations'][0]['Instances'][0]['NetworkInterfaces'][0]['PrivateIpAddress'];
          }
          # Sort the resulting array of IPs so they're in order
          asort($instance_ips);
          # Set the roles
          $GLOBALS['roles'] = array(
            'app_all' => $instance_ips,
            'app_ips' => $instance_ips,
            //'db_all' => array($host), @TODO: what about RDS?
            //'db_ips' => array($host)
            'app_primary' => array($instance_ips[0]),
            //'db_primary' => array($host),
            //'cache_all' => array($host), @TODO: and ElastiCache?
          );
          # Set 'host' as well
          $GLOBALS['host'] = array($instance_ips[0]);
        }
        else {
          $this->printTaskError("###### No AWS config found in the YAML file. Aborting!");
          exit("Aborting build!\n");
        }
      }
      # Build roles for a single server
      else {
        $host = $GLOBALS['host'];
        $host_ip = $GLOBALS['host_ip'];
        $this->printTaskSuccess("===> Not a cluster, setting all roles to $host");
        $GLOBALS['roles'] = array(
          'app_all' => array($host),
          'app_ips' => array($host_ip),
          'db_all' => array($host),
          'db_ips' => array($host_ip),
          'app_primary' => array($host),
          'db_primary' => array($host),
          'cache_all' => array($host),
        );
      }
  }

}