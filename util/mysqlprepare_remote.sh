#!/bin/bash
# Script that:
# - generates a database.. if one already exists, increment the db digit suffix
# - imports a database dump into that database
# - sets a GRANT with a user/pass
# - injects the appropriate database credentials into the settings.php of the site
#   varying the syntax depending on whether it's a drupal6 or drupal7 site



# Args that must be passed
DBHOST=$1
NEWDB=$2
# Easier to match user to db for now
PASS=$3
SITE_ROOT=$4
BRANCH=$5
DUMPFILE=$6
APP_HOSTS=$7

# MySQL privileged credentials
myFile='/etc/mysql/debian.cnf'
myUser=`grep user $myFile | awk '{print $3}' | uniq`
myPass=`grep password $myFile | awk '{print $3}' | uniq`

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $PASS ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]] || [[ -z $DUMPFILE ]]
then
  echo "Usage: $0 databasename databasepass site_root branch dumpfile"
  echo "Missing options. Exiting"
  exit 1
fi

if [[ -z $APP_HOSTS ]]; then
  APP_HOSTS=localhost
fi

#########################################################################
#
#  MySQL database generation
#
#########################################################################
# Try and create a database. If it already exists,
# increment a digit suffix until it works

COUNTER=0

DBLENGTH=${#NEWDB}
if [ "$DBLENGTH" -gt 16 ]; then
  # leave room for integer suffixes if need be
  NEWDB=${NEWDB:0:12}
fi

ORIGDB=$NEWDB

while [  $COUNTER -lt 99 ]; do
  DB=`ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no jenkins@$DBHOST "sudo mysql --defaults-file=/etc/mysql/debian.cnf -Bse 'show databases'| egrep \"^${NEWDB}$\""`
  if [ "$DB" = "$NEWDB" ]; then
    echo "The database $NEWDB already exists"
    let COUNTER=COUNTER+1
    NEWDB=${ORIGDB}_${COUNTER}
    continue
  else
    echo "Creating a database for $NEWDB"
    ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no jenkins@$DBHOST "sudo mysql --defaults-file=/etc/mysql/debian.cnf -e 'CREATE DATABASE \`${NEWDB}\`'" || exit 1
    echo "Generating a user/pass for database $NEWDB"
    for host in $(echo $APP_HOSTS | tr "," "\n"); do
      echo "sudo mysql --defaults-file=/etc/mysql/debian.cnf -e 'GRANT ALL ON \`${NEWDB}\`.* to \"${NEWDB}\"@\"${host}\" IDENTIFIED BY \"${PASS}\"'"
      ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no jenkins@$DBHOST "sudo mysql --defaults-file=/etc/mysql/debian.cnf -e 'GRANT ALL ON \`${NEWDB}\`.* to \"${NEWDB}\"@\"${host}\" IDENTIFIED BY \"${PASS}\"'" || exit 1
    done
    break
  fi
done

DB=`ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no jenkins@$DBHOST "sudo mysql --defaults-file=/etc/mysql/debian.cnf -Bse 'show databases'| egrep \"^${NEWDB}$\""`
# Only do any importing if the database exists ( we should have failed above )
if [ $? -eq 0 ]; then
  #########################################################################
  #
  # Import database dump into new database
  #
  #########################################################################
  if [ ! -z $DUMPFILE ]; then
    echo "Importing database dump $DUMPFILE into $NEWDB"
    if [ -f $DUMPFILE ]; then
      mysql -h $DBHOST -u$myUser -p$myPass $NEWDB < $DUMPFILE || exit 1
    fi
  fi

  #########################################################################
  #
  # Copy settings.php into place
  #
  #########################################################################
  if [ -f $SITE_ROOT/sites/default/default.settings.php ]; then
    cp $SITE_ROOT/sites/default/default.settings.php $SITE_ROOT/sites/default/settings.php
  else
    echo "Missing default.settings.php. Aborting!"
    exit 1
  fi

  if [ -d $SITE_ROOT/core ]; then
    cat >> $SITE_ROOT/sites/default/settings.php <<EOF
\$databases['default']['default'] = array (
  'database' => '$NEWDB',
  'username' => '$NEWDB',
  'password' => '$PASS',
  'prefix' => '',
  'host' => '$DBHOST',
  'port' => '',
  'namespace' => 'Drupal\\Core\\Database\\Driver\\mysql',
  'driver' => 'mysql',
);
\$config_directories['sync'] = '../config/sync';
\$file = '$SITE_ROOT/www/sites/default/$BRANCH.settings.php';
if (file_exists(\$file)) {
  include_once(\$file);
}
EOF
  elif [ -f $SITE_ROOT/modules/overlay/overlay.info ]; then
    cat >> $SITE_ROOT/sites/default/settings.php <<EOF
\$databases['default']['default'] = array(
 'driver' => 'mysql',
 'database' => '$NEWDB',
 'username' => '$NEWDB',
 'password' => '$PASS',
 'host' => '$DBHOST',
 );
\$file = '$SITE_ROOT/sites/default/$BRANCH.settings.php';
if (file_exists(\$file)) {
  include_once(\$file);
}
EOF
  else
    cat >> $SITE_ROOT/sites/default/settings.php <<EOF
\$db_url = 'mysql://$NEWDB:$PASS@$DBHOST/$NEWDB';
\$file = '$SITE_ROOT/sites/default/$BRANCH.settings.php';
if (file_exists(\$file)) {
  include_once(\$file);
}
EOF
  fi
  
else
  echo "Something went wrong and we couldn't import a database or populate settings.php. Maybe we couldn't create the database?"
fi
