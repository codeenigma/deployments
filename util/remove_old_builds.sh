#!/bin/bash

# Remove old builds/deployments created by Jenkins to keep disk usage down.
# Written by Pascal Morin / Miguel Jacq, October 2011

# Help text to show if missing args or RTFM
usage()
{
cat << EOF
usage: $0 options

This script removes old builds/deployments created by Jenkins, to keep disk usage down.

OPTIONS:
   -d   The path to the www root (usually /var/www)
   -r   Repository name to search on
   -b   Branch name to search on
   -k   Number of builds to keep (integer)
   -h   This help message
EOF
}

# Generate variables from args
while getopts d:r:b:k:h option
do
 case $option in
  d)
   WWWDIR=$OPTARG
   ;;
  r)
   REPO=$OPTARG
   ;;
  b)
   BRANCH=$OPTARG
   ;;
  k)
   KEEP=$OPTARG
   ;;
  h)
   usage
   exit
   ;;
 esac
done

# Check for arguments and exit if anything is missing
if [[ -z $WWWDIR ]] || [[ -z $REPO ]] || [[ -z $BRANCH ]] || [[ -z $KEEP ]]
then
  usage
  exit 1
fi

# The magic to remove the old builds
PATTERN=$REPO'_'$BRANCH'_build_*'
REMAINING=`find -L $WWWDIR -maxdepth 1 -type d -name "$PATTERN" | wc -l`
if [ $REMAINING -eq 0 ]; then
  echo "Didn't find any builds. Exiting"
  exit
fi
SUFFIX=0

while [ $REMAINING -gt $KEEP ]; do
  REMOVE=$WWWDIR'/'$REPO'_'$BRANCH'_build_'$SUFFIX
  if [ -d "$REMOVE" ]; then
    echo "Removing $BRANCH build $SUFFIX for $REPO"
    rm -rf $REMOVE || exit 1
  fi
  REMAINING=`find $WWWDIR -maxdepth 1 -type d -name "$PATTERN" | wc -l`
  let SUFFIX=SUFFIX+1
done
