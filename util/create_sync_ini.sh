#!/bin/bash

SHORTNAME=
HOST=
USER=
SYNCFILE=

usage() {
cat << EOF
usage: $0 OPTIONS

Use this script to generate a sync.ini for use by Jenkins/Fabric
when connecting to remote production environments in order to
sync from them.

OPTIONS:
   -s   Short name of your site. Typically the 'project identifier'
   -h   Production host to sync from
   -u   User to connect to the production host as.
   -f   File to write the sync.ini to. Typically WORKSPACE/sync.ini where WORKSPACE is that of the Jenkins sync job.
EOF
}

while getopts "s:h:u:f:" OPTION
do
  case $OPTION in
    s)
      SHORTNAME=$OPTARG
      ;;
    h)
      HOST=$OPTARG
      ;;
    u)
      USER=$OPTARG
      ;;
    f)
      SYNCFILE=$OPTARG
      ;;
    ?)
      exit
      ;;
  esac
done

if [[ -z $SHORTNAME || -z $HOST || -z $USER || -z $SYNCFILE ]]; then
  echo "Missing arguments!"
  usage
  exit 1
fi

echo -e "
[$SHORTNAME]
host=$HOST
user=$USER
"| tee $SYNCFILE > /dev/null || exit 1
