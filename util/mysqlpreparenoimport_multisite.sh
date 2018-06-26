#!/bin/bash
# Script that:
# - generates a database.. if one already exists, increment the db digit suffix
# - imports a database dump into that database
# - sets a GRANT with a user/pass 
# - injects the appropriate database credentials into the settings.php of the site
#   varying the syntax depending on whether it's a drupal6 or drupal7 site

# MySQL privileged credentials
myFile='/etc/mysql/debian.cnf'
myUser=`grep user $myFile | awk '{print $3}' | uniq`
myPass=`grep password $myFile | awk '{print $3}' | uniq`


# Args that must be passed
NEWDB=$1
# Easier to match user to db for now
PASS=$2
SITE_ROOT=$3
BRANCH=$4
URL=$5
D8=$6

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $PASS ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]] || [[ -z $URL ]]
then
  echo "Usage: $0 databasename databasepass site_root branch url"
  echo "Missing options. Exiting"
  exit 1
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
if [ "$DBLENGTH" -gt 14 ]; then
  # leave room for integer suffixes if need be
  NEWDB=${NEWDB:0:12}
fi

ORIGDB=$NEWDB

while [  $COUNTER -lt 99 ]; do
  DB=`mysql -u$myUser -p$myPass -Bse 'show databases'| egrep "^${NEWDB}$"`
  if [ "$DB" = "$NEWDB" ]; then
    echo "The database $NEWDB already exists"
    let COUNTER=COUNTER+1
    NEWDB=${ORIGDB}_${COUNTER}
    continue
  else
    echo "Creating a database for $NEWDB"
    mysqladmin -u$myUser -p$myPass create $NEWDB || exit 1
    echo "Generating a user/pass for database $NEWDB"
    mysql -u$myUser -p$myPass -e "GRANT ALL ON \`$NEWDB\`.* to '$NEWDB'@'localhost' IDENTIFIED BY '$PASS'" || exit 1
    break
  fi
done

DB=`mysql -u$myUser -p$myPass -Bse 'show databases'| egrep "^${NEWDB}$"`
# Only do any importing if the database exists ( we should have failed above
if [ $? -eq 0 ]; then
  #########################################################################
  #
  # Inject the database credentials into the site's settings.php
  #
  #########################################################################
  if [ -f $SITE_ROOT/sites/$URL/default.settings.php ]; then
    cp $SITE_ROOT/sites/$URL/default.settings.php $SITE_ROOT/sites/$URL/settings.php
  else
    echo "Missing default.settings.php. Aborting!"
    exit 1
  fi

  #########################################################################
  #
  # Drush site install.
  #
  #########################################################################

  cd $SITE_ROOT/sites/$URL
  DBURL="mysql://$NEWDB:$PASS@localhost:3306/$NEWDB"
  echo $DBURL
  drush si -y --db-url=$DBURL --sites-subdir=$URL

  #########################################################################
  #
  # Check for and include $branch.settings.php.
  #
  #########################################################################

  cat >> $SITE_ROOT/sites/$URL/settings.php <<EOF
\$config_directories['sync'] = '../config/sync';
\$file = '$SITE_ROOT/sites/$URL/$BRANCH.settings.php';
if (file_exists(\$file)) {
  include(\$file);
}
EOF

else
  echo "Something went wrong and we couldn't import a database or populate settings.php. Maybe we couldn't create the database?"
fi
