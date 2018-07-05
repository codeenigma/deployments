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
      $links_from = \Robo\Robo::Config()->get("command.build.$build_type.app.links.from");
      $links_to = \Robo\Robo::Config()->get("command.build.$build_type.app.links.to");
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

}