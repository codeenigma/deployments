#!/bin/bash
# Script that:
# - injects the appropriate database credentials into the settings.php of the site
#   varying the syntax depending on whether it's a drupal 6 or newer site

# Args that must be passed
NEWDB=$1
PASS=$2
SITE_ROOT=$3
BRANCH=$4
PROFILE=$5
DBHOST=$6
DBUSER=$7
MYSQL_CONFIG=$8
DUMPFILE=$9

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $PASS ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]]
then
  echo "Usage: $0 databasename databasepass site_root branch"
  echo "Missing options. Exiting"
  exit 1
fi

# Assume all one server unless told otherwise
if [[ -z $DBHOST ]]; then
  DBHOST=localhost
fi

# Assume 'minimal' profile if not supplied
if [[ -z $PROFILE ]]; then
  PROFILE=minimal
fi

# MySQL privileged credentials
# If no path provided, assume Debian default
if [[ -z $MYSQL_CONFIG ]]; then
  MYSQL_CONFIG='/etc/mysql/debian.cnf'
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

#########################################################################
#
# Drush site install.
#
#########################################################################

if [[ -z $DBUSER ]]; then
  DBUSER=$NEWDB
else
  # make sure provided db username is not too long
  DBUSER=${DBUSER:0:32}
fi

cd $SITE_ROOT/sites/default
DBURL="mysql://$DBUSER:$PASS@$DBHOST/$NEWDB"
echo $DBURL
drush si $PROFILE -y --db-url=$DBURL

chmod 644 $SITE_ROOT/sites/default/settings.php

#########################################################################
#
# Check for and include $branch.settings.php.
#
#########################################################################

cat >> $SITE_ROOT/sites/default/settings.php <<EOF
\$config_directories['sync'] = '../config/sync';
\$file = '$SITE_ROOT/sites/default/$BRANCH.settings.php';
if (file_exists(\$file)) {
  include_once(\$file);
}
EOF

#########################################################################
#
# Import database dump into new database
#
# Note: if this is Drupal 8 you will import here instead of in
# mysqlprepare.sh - it will fail if you attempt an import earlier!
#
#########################################################################
if [ ! -z $DUMPFILE ]; then
  echo "Importing database dump $DUMPFILE into $NEWDB"
  if [ -f $DUMPFILE ]; then
    mysql --defaults-file=${MYSQL_CONFIG} $NEWDB < $DUMPFILE || exit 1
  fi
fi
