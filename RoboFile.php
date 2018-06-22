<?php
/**
 * This is project's console commands configuration for Robo task runner.
 *
 * @see http://robo.li/
 */
class RoboFile extends \Robo\Tasks
{
  // define public methods as commands
  function hello($world, $opts = ['silent|s' => false]) {
    if (!$opts['silent']) $this->say("Hello $world!");
  }

  function build(
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
    include('./common/Config.php');
    # Variables that can be set in the YAML file
    $GLOBALS['ci_user']    = return_config_item($buildtype, 'server', 'ci-user');
    $www_root              = return_config_item($buildtype, 'server', 'www-root');
    $ssh_key               = return_config_item($buildtype, 'server', 'ssh-key');
    $notifications_email   = return_config_item($buildtype, 'app', 'notifications-email');
    $app_location          = return_config_item($buildtype, 'app', 'location', 'string', 'www');
    # Fixed variables
    $GLOBALS['build_path'] = $www_root . '/' . $repo . '_' . $buildtype . '_build_' . $build;
    $GLOBALS['app_path']   = $GLOBALS['build_path'] . '/' . $app_location;
    # Debug feedback
    print "===> Build path set to ". $GLOBALS['build_path'] . "\n";
    print "===> App path set to ". $GLOBALS['app_path'] . "\n";

    include('./common/Utils.php');
    define_host($buildtype);
    define_roles($cluster);
    perform_client_deploy_hook($repo, $build, $buildtype, 'pre', 'app_primary');
  }
}
