#!/bin/bash
# Script that:
# - generates a database.. if one already exists, increment the db digit suffix
# - imports a database dump into that database
# - sets a GRANT with a user/pass 
# - injects the appropriate database credentials into the wp-config.php of the site

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
DUMPFILE=$5

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $PASS ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]]
then
  echo "Usage: $0 databasename databasepass site_root branch dumpfile"
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
if [ "$DBLENGTH" -gt 16 ]; then
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
  # Import database dump into new database
  #
  #########################################################################
  if [ ! -z $DUMPFILE ]; then
    echo "Importing database dump $DUMPFILE into $NEWDB"
    if [ -f $DUMPFILE ]; then
      mysql -u$myUser -p$myPass $NEWDB < $DUMPFILE || exit 1
    fi
  fi



  #########################################################################
  #
  # Inject the database credentials into the site's wp-config.php
  #
  #########################################################################
  if [ -f $SITE_ROOT/wp-config.php.$BRANCH ]; then
    cp $SITE_ROOT/wp-config.php.$BRANCH $SITE_ROOT/wp-config.php
  else
    echo "No wp-config.php.$BRANCH file, continuing..."
  fi

  wp --path=$SITE_ROOT --allow-root core config --dbname=$NEWDB --dbuser=$NEWDB --dbpass=$PASS

else
  echo "Something went wrong and we couldn't import a database or populate wp-config.php. Maybe we couldn't create the database?"
fi
