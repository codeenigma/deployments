from fabric.api import *
from fabric.contrib.files import sed
import random
import string
# Custom Code Enigma modules
import common.Utils
# Needed to get variables set in modules back into the main script
from common.Utils import *
from Symfony import *


@task
@roles('app_primary')
def initial_config(repo, buildtype, build):
  print "===> Looks like a first build, preparing common files and directories..."
  if not exists("/var/www/shared"):
    if sudo("mkdir /var/www/shared").failed:
      raise SystemExit("There was no 'shared' directory on the server and we could not create it either")
    else:
      print "==> Created a new /var/www/shared directory for shared assets on this server"
  if sudo("mkdir /var/www/shared/%s_%s_logs" % (repo, buildtype)).failed:
    raise SystemExit("Could not create logs directory")
  if sudo("mkdir /var/www/shared/%s_%s_sessions" % (repo, buildtype)).failed:
    raise SystemExit("Could not create sessions directory")
  if sudo("mkdir /var/www/shared/%s_%s_data" % (repo, buildtype)).failed:
    raise SystemExit("Could not create data directory")
  if sudo("mkdir /var/www/shared/%s_%s_uploads" % (repo, buildtype)).failed:
    raise SystemExit("Could not create uploads directory")
  print "===> Directories all set"