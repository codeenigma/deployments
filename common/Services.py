from fabric.api import *


# Restart services
# yes, || exit 0 is weird, but apparently necessary as run()
# (or Jenkins) evaluates the possibility of running the 'false'
# action even if it's not going to return false.. stupid

@task
def clear_varnish_cache():
  with settings(hide('warnings', 'stderr'), warn_only=True):
    if run('pgrep -lf varnish | egrep -v "bash|grep" > /dev/null').return_code == 0:
      print "===> Purge Varnish cache without restarting"
      varnish_version = run("sudo varnishd -V 2>&1 | grep 'varnish-' | awk {'print $2'} | cut -d- -f2 | cut -d. -f1")
      if varnish_version == "4" or varnish_version == "6":
        sudo("varnishadm \"ban req.url ~ '.'\"")
      else:
        sudo("varnishadm \"ban.url .\"")

@task
def clear_php_cache():
  with settings(hide('warnings', 'stderr'), warn_only=True):
    print "===> Clearing PHP opcode cache"
    # Detect PHP version
    php_version = run("php -v | head -1 | awk {'print $2'} | cut -d. -f1,2")
    if any(version in php_version for version in [ '5.3', '5.4' ]):
      # clear the APC cache with PHP
      run('php -r "apc_clear_cache();"')
      run('php -r "apc_clear_cache(\"user\");"')
    else:
      # clear the opcache with PHP
      run('cachetool -n opcache:reset')

@task
def reload_webserver():
  with settings(hide('warnings', 'stderr'), warn_only=True):
    print "===> Reloading webserver"
    services = ['apache2', 'httpd', 'nginx']
    for service in services:
      if run('pgrep -lf %s | egrep -v "bash|grep" > /dev/null' % service).return_code == 0:
        run("sudo service %s reload" % service)

@task
def determine_webserver():
  # First determine the webserver
  webserver = "nginx"
  with settings(hide('running', 'warnings', 'stdout', 'stderr'), warn_only=True):
    services = ['apache2', 'httpd']
    for service in services:
      if run('pgrep -lf %s | egrep -v "bash|grep" > /dev/null' % service).return_code == 0:
        webserver = service
  return webserver