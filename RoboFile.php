<?php
/**
 * This is project's console commands configuration for Robo task runner.
 *
 * @see http://robo.li/
 */

use CodeEnigma\Deployments\Robo\common\loadTasks as CommonTasks;
use Robo\Tasks;

class RoboFile extends Tasks
{
  use CommonTasks;

  // define public methods as commands
  public function build(
    $repo,
    $repourl,
    $branch,
    $buildtype,
    $build,
    $keepbuilds = 10,
    $app_url = null,
    $cluster = false,
    $php_ini_file = null
    ) {
      # Off we go!
      $this->yell("Starting a build");
      # We want to stop if this fails anywhere!
      $this->stopOnFail(true);
      $this->_copy('../../../robo.yml', './robo.yml');
      $this->say("Moved our robo.yml file to the right place");

      # Load in our config
      $this->say("Setting up the environment");
      $GLOBALS['ci_user']    = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'ci-user');
      $www_root              = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'www-root');
      $ssh_key               = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'ssh-key');
      $notifications_email   = $this->taskConfig()->returnConfigItem($buildtype, 'app', 'notifications-email');
      $app_location          = $this->taskConfig()->returnConfigItem($buildtype, 'app', 'location', 'string', 'www');
      # Fixed variables
      $GLOBALS['build_path'] = $www_root . '/' . $repo . '_' . $buildtype . '_build_' . (string)$build;
      if ($app_location) {
        $GLOBALS['app_path'] = $GLOBALS['build_path'] . '/' . $app_location;
      }
      else {
        $GLOBALS['app_path'] = $GLOBALS['build_path'];
      }
      # Debug feedback
      $this->say("Build path set to '". $GLOBALS['build_path'] . "'");
      $this->say("App path set to '". $GLOBALS['app_path'] . "'");

      # Build our host and roles
      $this->taskDeployUtilsTasks()->defineHost($buildtype);
      $this->taskDeployUtilsTasks()->defineRoles($cluster);

      # Check out the code
      # We have to do this before the build hook so it's present on the server
      $gitTask = $this->taskGitStack()
       ->cloneRepo($repourl, $GLOBALS['build_path'], $branch);
      $result = $this->taskSshExec($GLOBALS['host'])
       ->remoteDir($GLOBALS['build_path'])
       ->exec($gitTask)
       ->run();
      if ($result->wasSuccessful()) {
        $this->say("Cloned repository from $repourl to " . $GLOBALS['build_path']);
      }

      # Give developers an opportunity to inject some code
      #$this->taskDeployUtilsTasks()->performClientDeployHook($repo, $build, $buildtype, 'pre', 'app_primary');
  }
}
