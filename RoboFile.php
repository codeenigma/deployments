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
  #use CommonTasks;

  // define public methods as commands
  /**
   * Deploy code to a remote server or servers
   *
   * @param string $project_name The short name for this project used in the paths on the server
   * @param string $repo_url The URL of the Git repository where the code is kept
   * @param string $branch The branch of the Git repository to build from
   * @param string $build_type The type of build (can be anything, typically develop, stage, live, etc.)
   * @param int $build The current build number (should be unique and incremented from the previous build)
   * @param int $keep_builds The number of builds to retain on the application servers
   * @param string $app_url The URL of the application being deployed
   * @param boolean $handle_vhosts Flag to tell us if we should try to configure the web server or not
   * @param boolean $cluster Flag to tell us if there is more than one server
   * @param boolean $autoscale Flag to tell us if this is an AWS autoscale layout
   * @param string $php_ini_file The path of the PHP ini file to use
   */
  public function build(
    $project_name,
    $repo_url,
    $branch,
    $build_type,
    $build,
    $keep_builds = 10,
    $app_url = "",
    $handle_vhosts = true,
    $cluster = false,
    $autoscale = false,
    $base_domain = "codeenigma.net",
    $php_ini_file = ""
    ) {
      # Off we go!
      $this->yell("Starting a build");

      /*
       * PREPARATION STAGE
       */

      # The actual working directory of our build is a few levels up from where we are
      $GLOBALS['build_cwd']    = getcwd() . '/../../..';
      # Move our config to the right place for Robo.li to auto-detect
      $this->say("Moving our robo.yml file to the Robo.li directory");
      $this->_copy($GLOBALS['build_cwd'] . '/robo.yml', './robo.yml');

      # Set web server root and app location
      $GLOBALS['www_root']   = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'www-root', '/var/www');
      $app_location          = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'location', 'www');
      # Fixed variables
      $GLOBALS['build_path'] = $GLOBALS['www_root'] . '/' . $project_name . '_' . $build_type . '_build_' . (string)$build;
      if ($app_location) {
        $GLOBALS['app_path'] = $GLOBALS['build_path'] . '/' . $app_location;
      }
      else {
        $GLOBALS['app_path'] = $GLOBALS['build_path'];
      }

      # Load in our config
      $this->say("Setting up the environment");
      # Set up server environment information
      $GLOBALS['ci_user']    = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'ci-user');
      $ssh_key               = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'ssh-key');
      # Set up web server - defaults to config for Nginx on Debian
      $web_server_restart    = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'web-server-restart', '/etc/init.d/nginx reload');
      $vhost_base_location   = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'vhost-base-location', '/etc/nginx/sites-available');
      $vhost_link_location   = $this->taskConfigTasks()->returnConfigItem($build_type, 'server', 'vhost-link-location', '/etc/nginx/sites-enabled');
      # Set up application information
      $notifications_email   = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'notifications-email');
      $app_link              = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'link', $GLOBALS['www_root'] . '/live.' . $project_name . '.' . $build_type);
      $app_port              = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'port', "80");
      # Figure out the URL for this application
      $app_url = $this->taskConfigTasks()->returnConfigItem($build_type, 'app', 'url', $app_url);
      if (!$app_url) {
        $app_url = strtolower("$project_name-$buildtype.$base_domain");
      }

      # Debug feedback
      $this->say("Build path set to '". $GLOBALS['build_path'] . "'");
      $this->say("App path set to '". $GLOBALS['app_path'] . "'");

      # Build our host and roles
      $this->taskConfigTasks()->defineHost($build_type, $autoscale);
      $this->taskConfigTasks()->defineRoles($cluster, $build_type);

      /*
       * APPLICATION DEPLOYMENT STAGE
       */

      # Create build directory
      $this->taskServerTasks()->createBuildDirectory();
      # Check out the code
      # We have to do this before the build hook so it's present on the server
      $this->taskServerTasks()->cloneRepo($repo_url, $branch);
      # Give developers an opportunity to inject some code
      $this->taskUtils()->performClientDeployHook($project_name, $build, $build_type, 'pre');
      # Adjust links to builds
      $this->taskServerTasks()->setLink($GLOBALS['build_path'], $app_link);
      # Add any other links specified in the YAML file
      $this->taskServerTasks()->setLinks($build_type);
      # Give developers an opportunity to inject some code again
      $this->taskUtils()->performClientDeployHook($project_name, $build, $build_type, 'post');

      /*
       * SERVER CONFIGURATION STAGE
       */

      # @TODO: We need a mechanism for developers to provide configs to include and
      # a path to place them at on the server
      # E.g. they might provide a web server config that depends on an included config existing (like magento)

      # Set up virtual host(s)
      if ($handle_vhosts) {
        $this->taskServerTasks()->createVhost($project_name, $build_type, $app_url, $app_link, $app_port, $web_server_restart, $vhost_base_location, $vhost_link_location);
      }

      /*
       * POST-BUILD STAGE
       */

      # Wrap it up!
      $this->yell("Build succeeded!");
      # Clean up old builds
      $this->taskUtils()->removeOldBuilds($project_name, $build_type, $build, $keep_builds);
  }

  public function destroy(

    ) {

  }
}
