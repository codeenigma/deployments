<?php
namespace CodeEnigma\Deployments\Robo\common;

# Required for outputting messages from custom tasks
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;
use Robo\LoadAllTasks;
use Robo\Tasks;
# Required so Robo::logger() is available
use Robo\Robo;

class ServerTasks extends Tasks implements TaskInterface
{
  use TaskIO;
  use LoadAllTasks;
  use loadTasks;

  public function __construct() {}
  public function run() {}

  /**
   * Function to create the target directory for this build
   *
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function createBuildDirectory(
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      foreach ($servers as $server) {
        $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
          ->exec('sudo mkdir -p ' . $GLOBALS['build_path'])
          ->exec('sudo chown ' . $GLOBALS['ci_user'] . ':' . $GLOBALS['ci_user'] . ' ' . $GLOBALS['build_path'])
          ->run();
        if (!$result->wasSuccessful()) {
          $this->printTaskError("###### Could not create build directory on $server");
          exit("Aborting build!\n");
        }
      }
  }

  /**
   * Function to clone the repository to the app servers
   *
   * @param string $repo_url The URL of the Git repository to clone
   * @param string $branch Git branch to clone
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function cloneRepo(
    $repo_url,
    $branch,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      foreach ($servers as $server) {
        $gitTask = $this->taskGitStack()
          ->cloneRepo($repo_url, $GLOBALS['build_path'], $branch);
        $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
          ->remoteDir($GLOBALS['build_path'])
          ->exec($gitTask)
          ->run();
        if ($result->wasSuccessful()) {
          $this->printTaskSuccess("===> Cloned repository from $repo_url to " . $GLOBALS['build_path'] . " on $server");
        }
        else {
          $this->printTaskError("###### Could not clone repository from $repo_url to " . $GLOBALS['build_path'] . " on $server");
          exit("Aborting build!\n");
        }
      }
  }

  /**
   * Helper function to create a symbolic link to a directory
   *
   * @param string $from Path of directory to link to
   * @param string $to Path of link to create
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function setLink(
    $from,
    $to,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      foreach ($servers as $server) {
        $this->printTaskSuccess("===> Updating links on $server");
        $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
          ->exec("stat $to")
          ->run();
        if ($result->wasSuccessful()) {
          $this->printTaskSuccess("===> Removing existing link on $server");
          $this->taskSshExec($server, $GLOBALS['ci_user'])
            ->exec("sudo unlink $to")
            ->run();
        }
        $this->printTaskSuccess("===> Creating new link on $server");
        $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
          ->exec("sudo ln -s $from $to")
          ->run();
        if (!$result->wasSuccessful()) {
          $this->printTaskError("###### Failed to set link $to on $server");
          exit("Aborting build!\n");
        }
      }
  }

  /**
   * Helper function wrapping setLink() to parse multiple links in the config YAML
   *
   * @param string $build_type
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function setLinks(
    $build_type,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      $links = $links_from = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'links');
      $links_from = $links['from'];
      $links_to = $links['to'];
      if ($links_from) {
        $this->printTaskSuccess("===> Fetching and setting links defined in YAML for '$build_type'");
        foreach ($links_from as $link_index => $link_from) {
          foreach ($servers as $server) {
            $this->setLink($link_from, $links_to[$link_index]);
          }
        }
        $this->printTaskSuccess("===> Finished with links defined in YAML");
      }
      else {
        $this->printTaskSuccess("===> No links defined in YAML for the '$build_type' build");
      }
  }

  /**
   * Function for creating a virtual host for the web server on each server in the 'app_all' role
   *
   * Note, this function assumes a template vhost has been provided in the project repository
   * This template vhost will be iterated over replacing token values with actual environment data
   * Those tokens are:
   *
   *  - app_url  - replaced with the contents of the $app_url variable
   *  - app_port - replaced with the contents of the $app_port variable
   *  - app_id   - replaced with the contents of the $app_id variable
   *  - app_link - replaced with the contents of the $app_link variable
   *  - app_ip   - replaced with the contents of the $app_id variable, generated in ConfigTasks::defineRoles()
   *
   *  You may disregard these replacement patterns if you do not need them, they are optional
   *
   * @param string $project_name
   * @param string $build_type
   * @param string $app_url
   * @param string $app_link
   * @param string $app_port The port the application should be served from
   * @param string $web_server_restart The command to execute to restart the web server
   * @param string $vhost_base_location The location the template should be copied to if no vhost exists yet
   * @param string $vhost_link_location The location the copied template should be linked to
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function createVhost(
    $project_name,
    $build_type,
    $app_url,
    $app_link,
    $app_port,
    $web_server_restart,
    $vhost_base_location,
    $vhost_link_location,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      $app_id = "$project_name.$build_type";
      # Check we have a template before continuing
      $vhost_template = $this->taskConfigTasks->returnConfigItem($build_type, 'server', 'vhost-template');
      if (!$vhost_template) {
        $this->printTaskError("###### No template found in config, aborting vhost creation");
        return;
      }
      # We do have a template, so let's try and use it
      foreach ($servers as $server_index => $server) {
        $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
          ->exec("stat $vhost_base_location/$app_url.conf")
          ->run();
        if ($result->wasSuccessful()) {
          $this->printTaskSuccess("===> The vhost $vhost_base_location/$app_url.conf already exists on $server, moving on");
        }
        else {
          $this->printTaskSuccess("===> Making a new vhost at $vhost_base_location/$app_url.conf on $server");
          # In case the replacement pattern is necessary, look up the IP of this server, if available
          $app_ip = $GLOBALS['roles']['app_ips'][$server_index];
          $app_ip_string = "$app_ip:443";
          # Copy the vhost template from the project and replace tokens with environment data
          # Note, even if 'sed' doesn't find the string it's still a bash 'success'
          $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
            ->exec("sudo cp $app_link/$vhost_template $vhost_base_location/$app_url.conf")
            ->exec("sudo sed -i s/app_url/$app_url/g $vhost_base_location/$app_url.conf")
            ->exec("sudo sed -i s/app_port/$app_port/g $vhost_base_location/$app_url.conf")
            ->exec("sudo sed -i s/app_id/$app_id/g $vhost_base_location/$app_url.conf")
            ->exec("sudo sed -i s/app_link/$app_link/g $vhost_base_location/$app_url.conf")
            ->exec("sudo sed -i s/app_ip:443/$app_ip_string/g $vhost_base_location/$app_url.conf")
            ->exec("sudo ln -s $vhost_base_location/$app_url.conf $vhost_link_location/$app_url.conf")
            ->exec("cat $vhost_link_location/$app_url.conf")
            ->exec("sudo $web_server_restart")
            ->run();
          if ($result->wasSuccessful()) {
            $this->printTaskSuccess("===> The vhost $vhost_base_location/$app_url.conf created on $server");
          }
          else {
            $this->printTaskError("###### Failed to create $vhost_base_location/$app_url.conf created on $server, please fix manually");
          }
        }
      }

    }

}