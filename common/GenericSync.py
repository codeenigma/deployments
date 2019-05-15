from fabric.api import *
import string

# Define a dictionary containing server roles
@task
def define_roles(source_server, target_server):
  all_servers = [source_server, target_server]
  env.roledefs = {
    'source': source_server,
    'target': target_server,
    'all': all_servers,
  }

  env.host = env.roledefs['source']
