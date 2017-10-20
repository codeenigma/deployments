from fabric.api import *
from fabric.contrib.files import sed
import string


# Small function to revert db
@task
def _revert_db(repo, branch, build):
  run("if [ -f ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz ]; then zcat ~jenkins/dbbackups/%s_%s_prior_to_%s.sql.gz | wp --allow-root --path=/var/www/%s_%s_%s/www db cli; fi" % (repo, branch, build, repo, branch, build, repo, branch, build))
