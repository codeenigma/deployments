#!/bin/bash
# Script that:
# - generates a database.. if one already exists, increment the db digit suffix
# - optionally imports a database dump into that database
# - sets a GRANT with a user/pass

# Args that must be passed
NEWDB=$1
PASS=$2
SITE_ROOT=$3
BRANCH=$4
DBHOST=$5
DBUSER=$6
MYSQL_CONFIG=$7
APP_HOSTS=$8

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $PASS ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]]
then
  echo "Usage: $0 databasename databasepass site_root branch"
  echo "Missing options. Exiting"
  exit 1
fi

# Assume all one server unless told otherwise
if [[ -z $APP_HOSTS ]]; then
  APP_HOSTS=localhost
fi

if [[ -z $DBHOST ]]; then
  DBHOST=localhost
fi

# MySQL privileged credentials
# If no path provided, assume Debian default
if [[ -z $MYSQL_CONFIG ]]; then
  MYSQL_CONFIG='/etc/mysql/debian.cnf'
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
if [ "$DBLENGTH" -gt 32 ]; then
  # leave room for integer suffixes if need be
  NEWDB=${NEWDB:0:28}
fi

if [[ -z $DBUSER ]]; then
  DBUSER=$NEWDB
else
  # make sure provided db username is not too long
  DBUSER=${DBUSER:0:32}
fi

ORIGDB=$NEWDB

while [ $COUNTER -lt 10 ]; do
  DB=$(sudo mysql --defaults-file=${MYSQL_CONFIG} -Bse 'show databases' | egrep "^${NEWDB}$")
  if [ "$DB" = "$NEWDB" ]; then
    echo "The database $NEWDB already exists."
    let COUNTER=COUNTER+1
    NEWDB=${ORIGDB}_${COUNTER}
    continue
  else
    echo "Creating a database for $NEWDB"
    sudo mysql --defaults-file=${MYSQL_CONFIG} -e "CREATE DATABASE \`${NEWDB}\`" || exit 1
    echo "Generating a user/pass for database $NEWDB"
    for host in $(echo $APP_HOSTS | tr "," "\n"); do
      echo "sudo mysql --defaults-file=${MYSQL_CONFIG} -e 'GRANT ALL ON \`${NEWDB}\`.* to \"${DBUSER}\"@\"${host}\" IDENTIFIED BY \"${PASS}\"'"
      sudo mysql --defaults-file=${MYSQL_CONFIG} -e "GRANT ALL ON \`${NEWDB}\`.* TO \"${DBUSER}\"@\"${host}\" IDENTIFIED BY \"${PASS}\""
    done
    break
  fi
done

DB=$(sudo mysql --defaults-file=${MYSQL_CONFIG} -Bse 'show databases' | egrep "^${NEWDB}$")

# Only do any importing if the database exists ( we should have failed above
if [ $? -eq 0 ]; then

  #########################################################################
  #
  # Import database dump into new database
  #
  #########################################################################
  if [ ! -z $DUMPFILE ]; then
    echo "Importing database dump $DUMPFILE into $DB"
    if [ -f $DUMPFILE ]; then
      mysql --defaults-file=${MYSQL_CONFIG} $DB < $DUMPFILE || exit 1
    fi
  fi

else
  echo "Something went wrong and we couldn't import a database. Maybe we couldn't create the database?"
fi

# We need the new database name back in case we want to use it later
echo $NEWDB
