from fabric.api import *
import sys
import time

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'


def pull_files(source_dir, source_addr, copy_user, copy_dir, now):
  print "===> Copy files from %s to local Jenkins server..." % source_addr
  if local("rsync -e 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' -aHPv %s@%s:%s/ %s/copy_%s/" % (copy_user, env.host, source_dir, copy_dir, now)).failed:
    SystemExit("Could not copy %s files from %s down to Jenkins server. Aborting." % (source_dir, source_addr))

  print "Files copied from %s on %s." % (source_dir, env.host)


def put_files(orig_host, source_dir, dest_dir, dest_user, dest_group, copy_user, copy_dir, now):
  env.host_string = orig_host

  print "===> Now copy files to destination, so switch back to original host..."

  if sudo("chown -R %s %s" % (copy_user, dest_dir)).failed:
    SystemExit("Could not set ownership to %s on destination directory %s correctly." % (copy_user, dest_dir))

  if local("rsync -aHPv %s/copy_%s/ %s:%s/" % (copy_dir, now, env.host_string, dest_dir)).failed:
    SystemExit("Could not copy %s files to destination %s. Aborting." % (source_dir, dest_dir))

  with settings(warn_only=True):
    if sudo("chown -R %s:%s %s" % (dest_user, dest_group, dest_dir)).failed:
      print "Could not set ownership to %s on %s on %s. Marking the build as unstable." % (dest_user, dest_dir, env.host)
      sys.exit(3)


def main(source_dir, source_addr, dest_user, dest_group=None, copy_user="jenkins", copy_dir="/tmp", dest_dir=None):
  if dest_dir is None:
    dest_dir = source_dir

  if dest_group is None:
    dest_group = dest_user

  orig_host = "%s@%s" % (env.user, env.host)

  # Swap to source to copy files to Jenkins server
  env.host = source_addr
  env.user = copy_user
  env.host_string = "%s@%s" % (env.user, env.host)

  # Get current timestamp, so we have a unique identifier
  now = time.strftime("%Y%m%d%H%M%S", time.gmtime())

  # Remove trailing slash from source_dir
  source_dir = source_dir.rstrip('/')

  pull_files(source_dir, source_addr, copy_user, copy_dir, now)
  put_files(orig_host, source_dir, dest_dir, dest_user, dest_group, copy_user, copy_dir, now)

  print "SUCCESS! Files copied."
