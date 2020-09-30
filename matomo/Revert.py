from fabric.api import *
from fabric.contrib.files import sed
import random
import string
import time
# Custom Code Enigma modules
import common.MySQL


# Small function to revert db
@task
@roles('app_primary')
def _revert_db(repo, branch, build, db_name):
  print "===> Reverting the database..."
  
  mysql_revert_db(db_name, build)

# Revert a MySQL database to a previously taken backup
@task
def mysql_revert_db(db_name, build, mysql_config='/etc/mysql/debian.cnf'):
  print "===> Dropping all tables"
  sudo("if [ -f /var/www/shared/dbbackups/%s_prior_to_%s.sql.gz ]; then mysql --defaults-file=%s -e 'drop database `%s`'; fi" % (db_name, build, mysql_config, db_name))
  sudo("mysql --defaults-file=%s -e 'create database `%s`'" % (mysql_config, db_name))
  print "===> Waiting 5 seconds to let MySQL internals catch up"
  time.sleep(5)
  print "===> Restoring the database from backup"
  sudo("if [ -f /var/www/shared/dbbackups/%s_prior_to_%s.sql.gz ]; then zcat ~jenkins/dbbackups/%s_prior_to_%s.sql.gz | sed -e 's/DEFINER[ ]*=[ ]*[^*]*\*/\*/' | mysql --defaults-file=%s -D %s; fi" % (db_name, build, db_name, build, mysql_config, db_name))
