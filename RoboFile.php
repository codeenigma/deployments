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
    $build_type,
    $build,
    $keep_builds = 10,
    $app_url = null,
    $cluster = false,
    $autoscale = null,
    $php_ini_file = null
    ) {
      # Off we go!
      $this->yell("Starting a build");
      # The actual working directory of our build is a few levels up from where we are
      $GLOBALS['build_cwd']    = getcwd() . '/../../..';
      # Move our config to the right place for Robo.li to auto-detect
      $this->say("Moving our robo.yml file to the Robo.li directory");
      $this->_copy($GLOBALS['build_cwd'] . '/robo.yml', './robo.yml');

      # Set web server root and app location
      $GLOBALS['www_root']   = $this->taskConfig()->returnConfigItem($build_type, 'server', 'www-root', '/var/www');
      $app_location          = $this->taskConfig()->returnConfigItem($build_type, 'app', 'location', 'www');
      # Fixed variables
      $GLOBALS['build_path'] = $GLOBALS['www_root'] . '/' . $repo . '_' . $build_type . '_build_' . (string)$build;
      if ($app_location) {
        $GLOBALS['app_path'] = $GLOBALS['build_path'] . '/' . $app_location;
      }
      else {
        $GLOBALS['app_path'] = $GLOBALS['build_path'];
      }

      # Load in our config
      $this->say("Setting up the environment");
      $GLOBALS['ci_user']    = $this->taskConfig()->returnConfigItem($build_type, 'server', 'ci-user');
      $ssh_key               = $this->taskConfig()->returnConfigItem($build_type, 'server', 'ssh-key');
      $notifications_email   = $this->taskConfig()->returnConfigItem($build_type, 'app', 'notifications-email');
      $app_link              = $this->taskConfig()->returnConfigItem($build_type, 'app', 'link', $GLOBALS['www_root'] . '/live.' . $repo . '.' . $build_type);


      # Debug feedback
      $this->say("Build path set to '". $GLOBALS['build_path'] . "'");
      $this->say("App path set to '". $GLOBALS['app_path'] . "'");

      # Build our host and roles
      $this->taskDeployUtilsTasks()->defineHost($build_type);
      $this->taskDeployUtilsTasks()->defineRoles($cluster);

      # Create build directory
      $this->taskDeployUtilsTasks()->createBuildDirectory();
      # Check out the code
      # We have to do this before the build hook so it's present on the server
      $this->taskDeployUtilsTasks()->cloneRepo($repo_url, $branch);
      # Give developers an opportunity to inject some code
      $this->taskDeployUtilsTasks()->performClientDeployHook($repo, $build, $build_type, 'pre', 'app_primary');
      # Adjust links to builds
      $this->taskDeployUtilsTasks()->setLink($GLOBALS['build_path'], $app_link);
      # Give developers an opportunity to inject some code again
      $this->taskDeployUtilsTasks()->performClientDeployHook($repo, $build, $build_type, 'post', 'app_primary');
      # Wrap it up!
      $this->yell("Build succeeded!");
      # Clean up old builds
      $this->taskDeployUtilsTasks()->removeOldBuilds($repo, $build_type, $build, $keep_builds);
  }
}
