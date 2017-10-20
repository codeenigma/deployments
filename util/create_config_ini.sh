#!/bin/bash

APPS=
DBS=
MEMCACHES=
IP=localhost
CONFFILE=
PRODFILE=
APPIPS=

usage() {
cat << EOF
usage: $0 OPTIONS

Use this script to generate a sync.ini for use by Jenkins/Fabric

OPTIONS
   -a   App servers in a list,like,this
   -d   DB servers in a list,like,this
   -m   Memcache servers in a list,like,this
   -i   IP address of the MySQL server that Drupal should connect to
   -f   File to write the config.ini to. Typically WORKSPACE/config.ini where WORKSPACE is that of the Jenkins job.
   -p   Optional prod file to include when writing to config.ini file in -f, typically WORKSPACE/prod.config.ini where WORKSPACE is that of the Jenkins job.
   -A   Optional app server IPs in a list,like,this. They should in the same order as the -a option.
EOF
}

while getopts "a:d:m:i:f:p:A:" OPTION
do
  case $OPTION in
    a)
      APPS=$OPTARG
      ;;
    d)
      DBS=$OPTARG
      ;;
    m)
      MEMCACHES=$OPTARG
      ;;
    i)
      IP=$OPTARG
      ;;
    f)
      CONFFILE=$OPTARG
      ;;
    p)
      PRODFILE=$OPTARG
      ;;
    A)
      APPIPS=$OPTARG
      ;;
    ?)
      exit
      ;;
  esac
done

if [[ -z $APPS || -z $DBS || -z $MEMCACHES || -z $CONFFILE ]]; then
  echo "Missing arguments!"
  usage
  exit 1
fi

# Remove any old config file that might be left over
rm -f $CONFFILE

# Split the comma-delimited strings into arrays
apps=$(echo $APPS | tr ",", "\n")
dbs=$(echo $DBS | tr ",", "\n")
memcaches=$(echo $MEMCACHES | tr ",", "\n")

# Add the app servers into an [Apps] section with an integer key
echo -e "[Apps]\n"| tee -a $CONFFILE > /dev/null || exit 1
COUNTER=0
for app in $apps; do
let COUNTER=COUNTER+1
echo -e "app$COUNTER=$app\n"| tee -a $CONFFILE > /dev/null || exit 1
done

# Add the db servers into an [Dbs] section with an integer key
echo -e "[Dbs]\n"| tee -a $CONFFILE > /dev/null || exit 1
COUNTER=0
for db in $dbs; do
let COUNTER=COUNTER+1
echo -e "db$COUNTER=$db\n"| tee -a $CONFFILE > /dev/null || exit 1
done

# Add the memcache servers into an [Memcaches] section with an integer key
echo -e "[Memcaches]\n"| tee -a $CONFFILE > /dev/null || exit 1
COUNTER=0
for memcache in $memcaches; do
let COUNTER=COUNTER+1
echo -e "memcache$COUNTER=$memcache\n"| tee -a $CONFFILE > /dev/null || exit 1
done

# Add the main DB host (often a floating IP) into an [DrupalDBHost] section with an integer key
echo -e "[DrupalDBHost]\n"| tee -a $CONFFILE > /dev/null || exit 1
echo -e "dbhost=$IP\n"| tee -a $CONFFILE > /dev/null || exit 1

if [[ ! -z $APPIPS ]]; then
  appips=$(echo $APPIPS | tr ",", "\n")
  echo -e "[AppIPs]\n"| tee -a $CONFFILE > /dev/null || exit 1
  COUNTER=0
  for appip in $appips; do
    let COUNTER=COUNTER+1
    echo -e "appip$COUNTER=$appip\n"| tee -a $CONFFILE > /dev/null || exit 1
  done
fi

# Add anything from prod.config.ini
if [ -f "$PRODFILE" ]
then
  cat $PRODFILE >> $CONFFILE || exit 1
fi
