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
    $buildtype
    ) {
      # When not extending BaseTask you must define a logger before using TaskIO methods
      $this->setLogger(Robo::logger());
      $host = \Robo\Robo::Config()->get('command.build.' . $buildtype . '.server.host');
      if ($host) {
        $this->printTaskSuccess("===> Host is $host");
        $GLOBALS['host'] = $host;
      }
      else {
        $this->printTaskError("###### No host specified. Aborting!");
        exit();
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

  public function performClientDeployHook(
    $repo,
    $build,
    $buildtype,
    $stage,
    $role = 'app_primary'
    ) {
      $this->setLogger(Robo::logger());
      $malicious_commands = array(
        '$GLOBALS',
        'rm -rf /',
        'ssh',
        'taskSshExec',
      );
      $this->printTaskSuccess("===> Looking for custom developer hooks at the $stage stage for $buildtype builds");
      $build_hooks = \Robo\Robo::Config()->get("command.build.$buildtype.hooks.$stage");
      if ($build_hooks) {
        $servers = $GLOBALS['roles'][$role];
        foreach ($build_hooks as $build_hook) {
          $hook_path = $GLOBALS['build_cwd'] . "/$build_hook";
          $hook_ext = pathinfo($hook_path, PATHINFO_EXTENSION);
          if (file_exists($hook_path)) {
            switch ($hook_ext) {
              case 'php':
                foreach ($servers as $server) {
                  $this->taskSshExec($server, $GLOBALS['ci_user'])
                  ->remoteDir($GLOBALS['build_path'])
                  ->exec("php $build_hook $repo $build $buildtype")
                  ->run();
                }
                $this->printTaskSuccess("===> PHP build hook '$build_hook' was executed");
                break;
              case 'sh':
                foreach ($servers as $server) {
                  $this->taskSshExec($server, $GLOBALS['ci_user'])
                  ->remoteDir($GLOBALS['build_path'])
                  ->exec("chmod +x ./$build_hook")
                  ->exec("./$build_hook $repo $build $buildtype")
                  ->run();
                }
                $this->printTaskSuccess("===> Bash build hook '$build_hook' was executed");
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

  public function setLink(
    $from,
    $to
    ) {
    $this->setLogger(Robo::logger());
    $this->printTaskSuccess("===> Updating links");
    $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
      ->exec("stat $to")
      ->run();
    if ($result->wasSuccessful()) {
      $this->printTaskSuccess("===> Removing existing link");
      $this->taskSshExec($server, $GLOBALS['ci_user'])
        ->exec("sudo unlink $to")
        ->run();
    }
    $this->printTaskSuccess("===> Creating new link");
    $this->taskSshExec($server, $GLOBALS['ci_user'])
      ->exec("sudo ln -s $from $to")
      ->run();
  }

}