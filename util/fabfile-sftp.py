from fabric.api import *
import time

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

@task
def main(source_dir, source_addr, user="jenkins", copy_dir="/tmp"):
  orig_host = "%s@%s" % (env.user, env.host)

  # Swap to source to copy files to Jenkins server
  env.host = source_addr
  env.user = user
  env.host_string = "%s@%s" % (env.user, env.host)

  # Get current timestamp, so we have a unique identifier
  now = time.strftime("%Y%m%d%H%M%S", time.gmtime())

  # Remove trailing slash from source_dir
  source_dir = source_dir.rstrip('/')

  print "===> Copy files from %s to local Jenkins server..." % source_addr
  if local("rsync -e 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' -aHPv %s@%s:%s/ %s/copy_%s/" % (user, env.host, source_dir, copy_dir, now)).failed:
    SystemExit("Could not copy %s files from %s down to Jenkins server. Aborting." % (source_dir, source_addr))

  print "===> Now copy files to destination, so switch back to original host..."
  
  env.host_string = orig_host

  if local("rsync -aHPv %s/copy_%s/ %s:%s/" % (copy_dir, now, env.host_string, source_dir)).failed:
    SystemExit("Could not copy %s files to destination. Aborting.")

  print "SUCCESS! Files copied."
