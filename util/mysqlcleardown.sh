#!/bin/bash
# Script that:
# -

# MySQL privileged credentials
myFile='/etc/mysql/debian.cnf'
myUser=`grep user $myFile | awk '{print $3}' | uniq`
myPass=`grep password $myFile | awk '{print $3}' | uniq`

# Args that must be passed
NEWDB=$1
# Easier to match user to db for now
PASS=`mkpasswd ratmonkey`
SITE_ROOT=$2
BRANCH=$3
PROFILE=$4

# Check for missing args
if [[ -z $NEWDB ]] || [[ -z $SITE_ROOT ]] || [[ -z $BRANCH ]]
then
  echo "Usage: $0 databasename site_root branch [profile]"
  echo "if [profile] is omitted, Standard will be used"
  echo "Missing options. Exiting"
  exit 1
fi

if [ -z $PROFILE ]
then
  PROFILE="standard"
fi

## Drop DB first
#
echo "Dropping database $NEWDB"
mysqladmin -f -u$myUser -p$myPass drop database if exists $NEWDB || exit 1

echo "Revoking grants"
mysqladmin -f -u$myUser -p$myPass revoke all on $NEWDB.* for '$NEWDB'@'localhost' || exit 1

echo "Creating a database for $NEWDB"
mysqladmin -f -u$myUser -p$myPass create $NEWDB || exit 1

echo "New Grants"
mysqladmin -f -u$myUser -p$myPass grant all on $NEWDB.* to '$NEWDB'@'localhost' identified by "$PASS" || exit 1

#########################################################################
#
# Drush site install.
#
#########################################################################

cd $SITE_ROOT/sites/default
DBURL="mysql://$NEWDB:$PASS@localhost/$NEWDB"
echo $DBURL
drush si $PROFILE -y --db-url=$DBURL

