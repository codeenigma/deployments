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

  /**
   * Allow developers to inject some PHP or Bash code into the build process
   * See the main 'build' command documentation for descriptions of variables
   *
   * @param string $project_name
   * @param int $build
   * @param string $build_type
   * @param string $stage The stage of the build the hooks are being executed at
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function performClientDeployHook(
    $project_name,
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
            $malicious_string_found = $this->detectMaliciousStrings($malicious_commands, "", $hook_path);
            if (!$malicious_string_found) {
              switch ($hook_ext) {
                case 'php':
                  foreach ($servers as $server) {
                    $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
                      ->remoteDir($GLOBALS['build_path'])
                      ->exec("php $build_hook $project_name $build $build_type")
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
                      ->exec("./$build_hook $project_name $build $build_type")
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
              $this->printTaskError("###### Potentially malicious string '$malicious_string_found' found in '$build_hook', skipping");
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

  /**
   * Helper function for detecting malicious strings in either string inputs or files
   *
   * @param array $malicious_strings An array of strings to check for`
   * @param string $input_string The string to check for malicious strings
   * @param string $check_location The location of the file to check
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   *
   * @return mixed $malicious_string_found Bad string found or false if nothing found
   */
  public function detectMaliciousStrings(
    $malicious_strings,
    $input_string="",
    $check_location="",
    $role = 'app_primary'
    ) {
      $this->setLogger(Robo::logger());
      $malicious_strings_found = false;
      if (!empty($malicious_strings)) {
        foreach ($malicious_strings as $disallowed) {
          if ($check_location) {
            $this->printTaskSuccess("===> Checking location $check_location for malicious strings");
            $servers = $GLOBALS['roles'][$role];
            foreach ($servers as $server) {
              $result = $this->taskSshExec($server, $GLOBALS['ci_user'])
                ->exec("grep -r $disallowed $check_location")
                ->run();
              if ($result->wasSuccessful()) {
                $this->printTaskError("###### We found '$disallowed' in the location $check_location on $server");
                $malicious_strings_found = $disallowed;
              }
            }
          }
          if ($input_string) {
            $this->printTaskSuccess("===> Checking provided string for malicious strings");
            $servers = $GLOBALS['roles'][$role];
            # We only want to check on a single server, as it's simply a string comparison
            $result = $this->taskSshExec($servers[0], $GLOBALS['ci_user'])
              ->exec("echo $input_string | grep '$disallowed'")
              ->run();
            if ($result->wasSuccessful()) {
              $this->printTaskError("###### We found '$disallowed' in the provided string");
              $malicious_strings_found = $disallowed;
            }
          }
        }
      }
      return $malicious_strings_found;
  }

  /**
   * Helper function for tidying up old builds on app servers
   * See the main 'build' command documentation for descriptions of variables
   *
   * @param string $project_name
   * @param string $build_type
   * @param int $build
   * @param int $keep_builds
   * @param string $role The server role to execute against, as set in ConfigTasks::defineRoles()
   */
  public function removeOldBuilds(
    $project_name,
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
            ->exec("PATTERN=$project_name'_'$build_type'_build_*'")
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
              ->exec("PATTERN=$project_name'_'$build_type'_build_*'")
              ->exec("REMAINING=`find " . $GLOBALS['www_root'] . " -maxdepth 1 -type d -name \"\$PATTERN\" | wc -l`")
              ->exec("SUFFIX=0")
              ->exec("while [ \$REMAINING -gt " . $keep_builds . " ]; do REMOVE=" . $GLOBALS['www_root'] . "'/'$project_name'_'$build_type'_build_'\$SUFFIX; if [ -d \"\$REMOVE\" ]; then sudo rm -rf \$REMOVE || exit 1; fi; REMAINING=`find " . $GLOBALS['www_root'] . " -maxdepth 1 -type d -name \"\$PATTERN\" | wc -l`; let SUFFIX=SUFFIX+1; done")
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