from fabric.api import *
import os
import sys
import random
import time
import string
import uuid
# Custom Code Enigma modules
import common.Utils
import DrupalUtils


def main(shortname, branch, bucket_name, method='zip', sanitise='yes'):
  print "===> You want to download a database dump for %s %s. Let's start by fetching a fresh database..." % (shortname, branch)

  try:
    DrupalUtils.get_database(shortname, branch, sanitise)
    common.Utils.s3_upload(shortname, branch, method, shortname, bucket_name)
  except:
    e = sys.exc_info()[1]
    raise SystemError(e)
