#!/bin/bash

usage()
{
cat << EOF
usage: $0 options

This script takes a database backup of a Symfony site.

OPTIONS:
  -d  Directory path
  -r  Repository name
  -b  Build type
  -n  Build number
  -h  This help message
EOF
}

# Generate variables from args
while getopts d:r:b:n:h option
do
  case $option in
    d)
      WWWDIR=$OPTARG
      ;;
    r)
      REPO=$OPTARG
      ;;
    b)
      BUILDTYPE=$OPTARG
      ;;
    n)
      BUILDNUM=$OPTARG
      ;;
    h)
      usage
      exit
      ;;
  esac
done

# Check for arguments and exit if anything is missing
if [[ -z $WWWDIR ]] || [[ -z $REPO ]] || [[ -z $BUILDTYPE ]] || [[ -z $BUILDNUM ]]
then
  usage
  exit 1
fi

# See http://stackoverflow.com/questions/59895/can-a-bash-script-tell-what-directory-its-stored-in/23905052#23905052

# Get database parameters
dbname=$(grep "database_name" $WWWDIR/app/config/parameters_$BUILDTYPE.yml | awk '{print $2}')
dbuser=$(grep "database_user" $WWWDIR/app/config/parameters_$BUILDTYPE.yml | awk '{print $2}')
dbpassword=$(grep "database_password" $WWWDIR/app/config/parameters_$BUILDTYPE.yml | awk '{print $2}')
dbhost=$(grep "database_host" $WWWDIR/app/config/parameters_$BUILDTYPE.yml | awk '{print $2}')

filename="/home/jenkins/dbbackups/${REPO}-${BUILDTYPE}_prior_to_${BUILDNUM}.sql"

echo "Export $dbname database"

mysqldump -h "$dbhost" -u "$dbuser" --password="$dbpassword" "$dbname" > "$filename"
gzip "$filename"

