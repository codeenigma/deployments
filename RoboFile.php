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
    $repo_url,
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
      # The actual working directory of our build is a few levels up from where we are
      $GLOBALS['build_cwd']    = getcwd() . '/../../..';
      # Move our config to the right place for Robo.li to auto-detect
      $this->say("Moving our robo.yml file to the Robo.li directory");
      $this->_copy($GLOBALS['build_cwd'] . '/robo.yml', './robo.yml');

      # Set web server root and app location
      $www_root              = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'www-root', 'string', '/var/www');
      $app_location          = $this->taskConfig()->returnConfigItem($buildtype, 'app', 'location', 'string', 'www');
      # Fixed variables
      $GLOBALS['build_path'] = $www_root . '/' . $repo . '_' . $buildtype . '_build_' . (string)$build;
      if ($app_location) {
        $GLOBALS['app_path'] = $GLOBALS['build_path'] . '/' . $app_location;
      }
      else {
        $GLOBALS['app_path'] = $GLOBALS['build_path'];
      }

      # Load in our config
      $this->say("Setting up the environment");
      $GLOBALS['ci_user']    = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'ci-user');
      $ssh_key               = $this->taskConfig()->returnConfigItem($buildtype, 'server', 'ssh-key');
      $notifications_email   = $this->taskConfig()->returnConfigItem($buildtype, 'app', 'notifications-email');
      $app_link              = $this->taskConfig()->returnConfigItem($buildtype, 'app', 'link', 'string', $www_root . '/live.' . $repo . '.' . $buildtype);


      # Debug feedback
      $this->say("Build path set to '". $GLOBALS['build_path'] . "'");
      $this->say("App path set to '". $GLOBALS['app_path'] . "'");

      # Build our host and roles
      $this->taskDeployUtilsTasks()->defineHost($buildtype);
      $this->taskDeployUtilsTasks()->defineRoles($cluster);

      # Create build directory
      $this->taskDeployUtilsTasks()->createBuildDirectory();
      # Check out the code
      # We have to do this before the build hook so it's present on the server
      $this->taskDeployUtilsTasks()->cloneRepo($repo_url, $branch);
      # Give developers an opportunity to inject some code
      $this->taskDeployUtilsTasks()->performClientDeployHook($repo, $build, $buildtype, 'pre', 'app_primary');
      # Adjust links to builds
      $this->taskDeployUtilsTasks()->setLink($GLOBALS['build_path'], $app_link);
  }
}
