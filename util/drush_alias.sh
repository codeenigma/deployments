#!/bin/bash

# Generate a Drush alias

SHORTNAME=$1
URI=$2
BRANCH=$3

mkdir -p /etc/drush

cat > /etc/drush/${SHORTNAME}_${BRANCH}.alias.drushrc.php <<EOF
<?php

\$aliases['${SHORTNAME}_${BRANCH}'] = array(
  'root' => '/var/www/live.${SHORTNAME}.${BRANCH}/www',
  'uri' => '${URI}',
);
EOF
