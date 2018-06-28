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

  public function createBuildDirectory(
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $servers = $GLOBALS['roles'][$role];
      foreach ($servers as $server) {
        $result = $this->taskSshExec($GLOBALS['host'], $GLOBALS['ci_user'])
          ->exec('sudo mkdir -p ' . $GLOBALS['build_path'])
          ->exec('sudo chown ' . $GLOBALS['ci_user'] . ':' . $GLOBALS['ci_user'] . ' ' . $GLOBALS['build_path'])
          ->run();
        if (!$result->wasSuccessful()) {
          $this->printTaskError("###### Could not create build directory on $server");
          exit("Aborting build!\n");
        }
      }
  }

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
        $result = $this->taskSshExec($GLOBALS['host'], $GLOBALS['ci_user'])
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

}