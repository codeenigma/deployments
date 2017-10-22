# Code Enigma Deployment Scripts

## Developer notes

To support a new type of application:

1. Make a new directory for the scripts within this directory (e.g.
'laravel').

2. Within the new directory create a symbolic link to the 'common'
directory (e.g. `ln -s common ../common`).

3. Create a fabfile.py file in your new directory for your main() 
function only.

4. Create a \_\_init__.py file in your new directory to force Fabric to
autoload any modules you create.

5. Create all functions (including 'main') using Fabric's inbuild Task
decorator - read: 
http://docs.fabfile.org/en/1.13/usage/tasks.html#the-task-decorator

6. Create new .py files in your new directory for each group of tasks
you wish to call in your main() function in fabfile.py, for example:

```
drupal
|
 -- __init__.py (required by Fabric to autoload modules)
 -- AdjustConfiguration.py (tasks for adjusting Drupal settings, etc.)
 -- Drupal.py (common Drupal tasks)
 -- fabfile.py (just the main() task)
 -- InitialBuild.py (tasks associated only with first run)
 -- Revert.py (tasks associated with reverting a build)
 -- Test.py (tasks associated with automated testing)
 -- common (link to ../common)
    |
     -- __init__.py
     -- ConfigFile.py
     -- Services.py
     -- Utils.py
```
     
7. If you create tasks that are useful in a broader context, for 
example service restarts on servers, add them to a .py file in the 
'common' directory. If there is not a suitably named .py file, you can
create one for the tasks you are making.

IMPORTANT: Do not use global variables, scope is hard to handle and 
unreliable - if you need to pass a value between Python modules, make
your function return a variable.


** PLEASE DO NOT EVER MAKE THESE JENKINS SCRIPTS CUSTOMER SPECIFIC **

## Supporting clusters

You can use the roles() decorator in your modules, it will work:
http://docs.fabfile.org/en/1.13/api/core/decorators.html#fabric.decorators.roles

However, we cannot assume all scripts will require or indeed desire 
roles being set for clusters, so if your task goes into a 'common' 
module please DO NOT use the roles() decorator.

If you need to call a task with roles and it does not have a decorator
attached, you can force it by using env.roledefs['your_role'] to pass
an array of hosts to the execute() function, for example:

execute(common.Services.clear_php_cache, hosts=env.roledefs['app_all'])

For a list of available roles, see the define_roles() task in 
common.Utils.

