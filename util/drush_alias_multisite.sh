#!/bin/bash

# Generate a Drush alias

SHORTNAME=$1
URI=$2
BRANCH=$3
PATH=$4

/bin/mkdir -p /etc/drush

/bin/cat > /etc/drush/${SHORTNAME}_${BRANCH}.alias.drushrc.php <<EOF
<?php

\$aliases['${SHORTNAME}_${BRANCH}'] = array(
  'root' => '${PATH}',
  'uri' => '${URI}',
);
EOF