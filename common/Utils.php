<?php
function define_host(
        $buildtype
) {
  $host = \Robo\Robo::Config()->get('command.build.' . $buildtype . '.server.host');
  if ($host) {
    print "\n===> Host is $host\n";
    $GLOBALS['host'] = $host;
  }
  else {
    exit("###### No host specified. Aborting!\n");
  }
}

function define_roles(
        $cluster,
        $autoscale = null,
        $aws_credentials = null,
        $aws_autoscale_group = null
) {
  if ($cluster && $autoscale) {
    exit("###### You cannot be both a traditional cluster and an autoscale layout. Aborting!\n");
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
    print "===> Not a cluster, setting all roles to $host\n";
    $GLOBALS['roles'] = array(
      'app_all' => array($host),
      'db_all' => array($host),
      'app_primary' => array($host),
      'db_primary' => array($host),
      'cache_all' => array($host),
    );
  }
}

function perform_client_deploy_hook(
        $repo,
        $build,
        $buildtype,
        $stage,
        $role = 'app_primary'
) {
  $cwd = getcwd();
  $malicious_commands = array(
    '$GLOBALS',
    'rm -rf /',
    'ssh',
    'taskSshExec',
  );
  print "===> Looking for custom developer hooks at the $stage stage for $buildtype builds\n";
  $build_hooks = \Robo\Robo::Config()->get("command.build.$buildtype.hooks.$stage");
  if ($build_hooks) {
    $servers = $GLOBALS['roles'][$role];
    foreach ($build_hooks as $build_hook) {
      $hook_path = "$cwd/$build_hook";
      if (file_exists($hook_path)) {
        foreach ($servers as $server) {
          $this->taskSshExec($server, $GLOBALS['ci_user'])
              ->remoteDir($GLOBALS['build_path'])
              ->exec("php $build_hook")
              ->run();
        }
      }
      else {
        print "###### Could not find build hook '$build_hook' in the build repository\n";
      }
    }
  }
  else {
    print "===> No hooks found\n";
  }

}
