<?php
namespace CodeEnigma\Deployments\Robo\common;

# Required for outputting messages from custom tasks
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;
use Robo\LoadAllTasks;
use Robo\Tasks;
# Required so Robo::logger() is available
use Robo\Robo;

class DeployUtilsTasks extends Tasks implements TaskInterface
{
  use TaskIO;
  use LoadAllTasks;

  public function __construct() {}
  public function run() {}

  public function defineHost(
    $build_type
    ) {
      # When not extending BaseTask you must define a logger before using TaskIO methods
      $this->setLogger(Robo::logger());
      $host = \Robo\Robo::Config()->get('command.build.' . $build_type . '.server.host');
      if ($host) {
        $this->printTaskSuccess("===> Host is $host");
        $GLOBALS['host'] = $host;
      }
      else {
        $this->printTaskError("###### No host specified. Aborting!");
        exit("Aborting build!");
      }
  }

  public function defineRoles(
    $cluster,
    $autoscale = null,
    $aws_credentials = null,
    $aws_autoscale_group = null
    ) {
      $this->setLogger(Robo::logger());
      if ($cluster && $autoscale) {
        $this->printTaskError("###### You cannot be both a traditional cluster and an autoscale layout. Aborting!");
        exit();
      }
      # Build roles for a traditional cluster
      if ($cluster) {

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
          exit("Aborting build!");
        }
      }
  }

  public function performClientDeployHook(
    $repo,
    $build,
    $build_type,
    $stage,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $malicious_commands = array(
        '$GLOBALS',
        'rm -rf /',
        'ssh',
        'taskSshExec',
      );
      $this->printTaskSuccess("===> Looking for custom developer hooks at the $stage stage for $build_type builds");
      $build_hooks = \Robo\Robo::Config()->get("command.build.$build_type.hooks.$stage");
      if ($build_hooks) {
        $servers = $GLOBALS['roles'][$role];
        foreach ($build_hooks as $build_hook) {
          $hook_path = $GLOBALS['build_cwd'] . "/$build_hook";
          $hook_ext = pathinfo($hook_path, PATHINFO_EXTENSION);
          if (file_exists($hook_path)) {
            switch ($hook_ext) {
              case 'php':
                foreach ($servers as $server) {
                  $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
                    ->remoteDir($GLOBALS['build_path'])
                    ->exec("php $build_hook $repo $build $build_type")
                    ->run();
                  if ($result->wasSuccessful()) {
                    $this->printTaskSuccess("===> PHP build hook '$build_hook' was executed on $server");
                  }
                  else {
                    $this->printTaskError("###### PHP build hook '$build_hook' failed to execute on $server");
                  }
                }
                $result = null;
                break;
              case 'sh':
                foreach ($servers as $server) {
                  $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
                    ->remoteDir($GLOBALS['build_path'])
                    ->exec("chmod +x ./$build_hook")
                    ->exec("./$build_hook $repo $build $build_type")
                    ->run();
                  if ($result->wasSuccessful()) {
                    $this->printTaskSuccess("===> Bash build hook '$build_hook' was executed on $server");
                  }
                  else {
                    $this->printTaskError("###### Bash build hook '$build_hook' failed to execute on $server");
                  }
                }
                break;
              default:
                $this->printTaskError("###### Cannot handle hooks of type '$hook_ext', skipping");
            }
          }
          else {
            $this->printTaskError("###### Could not find build hook '$build_hook' in the build repository");
          }
        }
      }
      else {
        $this->printTaskSuccess("===> No hooks found");
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
          exit("Aborting build!");
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
        exit("Aborting build!");
      }
    }
  }

  public function removeOldBuilds(
    $repo,
    $build_type,
    $keep_builds,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $this->printTaskSuccess("===> Removing all but the last $keep_builds builds to conserve disk space");
      $servers = $GLOBALS['roles'][$role];
      foreach ($servers as $server) {

      }
  }

}