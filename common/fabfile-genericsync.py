from fabric.api import *
import GenericSync

@task
def main(site_name, source_server, source_database, target_server, target_database, mysql_config='/etc/mysql/debian.cnf'):
  user = "jenkins"

  GenericSync.define_roles(source_server, target_server)

  env.host_string = '%s'@'%s' % (user, env.host)

  execute(GenericSync.fetch_source_db, site_name, source_database, mysql_config, hosts=env.roledefs['source'])
  execute(GenericSync.import_db, site_name, target_database, mysql_config, hosts=env.roledefs['target'])
  execute(GenericSync.clean_up, site_name, hosts=env.roledefs['all'])
