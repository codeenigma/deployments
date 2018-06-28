<?php
namespace CodeEnigma\Deployments\Robo\common;

# Required for outputting messages from custom tasks
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;
use Robo\LoadAllTasks;
use Robo\Tasks;
# Required so Robo::logger() is available
use Robo\Robo;

class Utils extends Tasks implements TaskInterface
{
  use TaskIO;
  use LoadAllTasks;

  public function __construct() {}
  public function run() {}

  public function performClientDeployHook(
    $repo,
    $build,
    $build_type,
    $stage,
    $role = 'app_all'
    ) {
      # When not extending BaseTask you must define a logger before using TaskIO methods
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

  public function removeOldBuilds(
    $repo,
    $build_type,
    $build,
    $keep_builds,
    $role = 'app_all'
    ) {
      $this->setLogger(Robo::logger());
      $this->printTaskSuccess("===> Removing all but the last $keep_builds builds to conserve disk space");
      $latest_keep_build = $build - $keep_builds;
      if ($latest_keep_build > 0) {
        $servers = $GLOBALS['roles'][$role];
        foreach ($servers as $server) {
          $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
            ->exec("PATTERN=$repo'_'$build_type'_build_*'")
            ->exec("REMAINING=`find " . $GLOBALS['www_root'] . " -maxdepth 1 -type d -name \"\$PATTERN\" | wc -l`")
            ->exec("if [ \$REMAINING -eq 0 ]; then exit; fi")
            ->run();
          if (!$result->wasSuccessful()) {
            $this->printTaskSuccess("===> No builds to delete on $server");
          }
          else {
            $result = null;
            $this->printTaskSuccess("===> Found builds to delete on $server");
            $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
              ->exec("PATTERN=$repo'_'$build_type'_build_*'")
              ->exec("REMAINING=`find " . $GLOBALS['www_root'] . " -maxdepth 1 -type d -name \"\$PATTERN\" | wc -l`")
              ->exec("SUFFIX=0")
              ->exec("while [ \$REMAINING -gt " . $keep_builds . " ]; do REMOVE=" . $GLOBALS['www_root'] . "'/'$repo'_'$build_type'_build_'\$SUFFIX; if [ -d \"\$REMOVE\" ]; then sudo rm -rf \$REMOVE || exit 1; fi; REMAINING=`find " . $GLOBALS['www_root'] . " -maxdepth 1 -type d -name \"\$PATTERN\" | wc -l`; let SUFFIX=SUFFIX+1; done")
              ->run();
            if (!$result->wasSuccessful()) {
              $this->printTaskError("===> Build tidy-up on $server may not have worked");
            }
            else {
              $this->printTaskSuccess("===> Builds tidied on $server");
            }
          }
        }
      }
      else{
        $this->printTaskSuccess("===> No builds to delete");
      }

  }

}