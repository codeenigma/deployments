from fabric.api import *
from fabric.contrib.files import *
# Load in Code Enigma custom modules
import common.MySQL

# Override the shell env variable in Fabric, so that we don't see
# pesky 'stdin is not a tty' messages when using sudo
env.shell = '/bin/bash -c'

# Copying a database from A to B
@task
def main(source_db_name, target_db_name, target_hostname):
  # Copy the source database
  common.MySQL.mysql_backup_db(source_db_name,"sync")
  # Copy the source database down to CI server
  local("scp %s:~/dbbackups/%s_prior_to_sync.sql.gz ~/" % (env.host, source_db_name))
  # Copy the source database back up to target server
  local("scp ~/%s_prior_to_sync.sql.gz %s:~/dbbackups/%s_prior_to_sync.sql.gz" % (source_db_name, target_hostname, target_db_name))
  # Remove the file on the CI server
  local("rm ~/%s_prior_to_sync.sql.gz" % source_db_name)
  # Switch to target server
  env.host = target_hostname
  # Backup target database, just in case!
  common.MySQL.mysql_backup_db(target_db_name,"sync")
  # Restore the source database over the target database
  common.MySQL.mysql_revert_db(target_db_name,"sync")
