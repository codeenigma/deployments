# Deployments

[Code Enigma](https://www.codeenigma.com)'s custom [Fabric](http://www.fabfile.org/) and shell scripts for deploying various PHP apps. We predominantly do this using [Jenkins CI](https://jenkins.io), however in principle, any system capable of triggering a shell command on a server with Fabric installed can be used as a trigger for these scripts.

These deployment scripts currently support:

* [Drupal](https://www.drupal.org)
* [WordPress](https://wordpress.com/)
* [Magento](https://magento.com/)
* [Symfony](https://symfony.com/)
* Flat HTML

# Features

Example configuration files for developers are a work in progress, but the Drupal 8 version is reasonably complete and can be found here:

https://github.com/codeenigma/example-drupal/blob/8.x/config.ini

Here is an overview of the kinds of things these build scripts allow you to do:

## General

* specify target server(s) in a repository config file
* stand up initial builds of WordPress and Drupal automatically
* provision of a "seed" database
* supports clusters of app servers
* optional automatic SSL configuration
* optional HTTP AUTH password protection
* build hooks - developers can insert their own Fabric and shell scripts into the process at various points
* rollback - automatically restore the previous version of an app if build fails
* [StatusCake](https://www.statuscake.com) integration allowing alert pausing during build

## Drupal

Because as a company we mostly specialise in Drupal, a lot of the best features of the current scripts are actually Drupal specific:

* first install from a specified install profile
* inject environment-specific Drupal settings safely
* [Behat](http://behat.org) tests - run Behat tests automatically using Selenium
* [Simpletest](http://www.simpletest.org) unit tests - run Simpletest automatically
* [Coder module](https://www.drupal.org/project/coder) support - automatically check code style when building
* [Features module](https://www.drupal.org/project/features) support - often used for configuration in code in Drupal 7
* [Read Only Mode module](https://www.drupal.org/project/readonlymode) support - for deployments without going offline
* [Environment Indicator module](https://www.drupal.org/project/environment_indicator) support - for colour-coded environment notification for administrators
* automated feature branching support
* Drupal 8 configuration importing and exporting
* Drupal 8 deployments with Composer
* database update handling
* automatic provisioning of Drush aliases
* automatic configuration of Drupal cron
* synchronise databases between environments
* obfuscate sensitive data

# Dependencies

In order to use these scripts you must meet the following criteria:

* Linux CI server with [Fabric](http://www.fabfile.org) installed
* a 'jenkins' user on the CI server which is used to trigger Fabric commands
* Linux target app server(s) (Debian will work best without modification)
* a 'jenkins' user with a home directory and public key of the CI user on target app server(s)
* passwordless sudo for the 'jenkins' user on the target app server(s)
* [Git](https://git-scm.com) installed on the target app server(s)
* [cachetool](https://github.com/gordalina/cachetool) for clearing the PHP opcode cache
* [AWS CLI](https://aws.amazon.com/cli/) for interacting with the AWS API from the Linux terminal
* [s3cmd](http://s3tools.org) for interacting with AWS S3 buckets from the Linux terminal
* [boto3](https://github.com/boto/boto3) for accessing the AWS CLI via Python

## Application specific dependencies

* [composer](https://getcomposer.org/) (Drupal > 8, Magento or Symfony)
* [drush](http://www.drush.org) (Drupal) - installed at `/usr/local/bin/drush`
* [wp-cli](http://wp-cli.org) (WordPress)
* [Ruby](https://www.ruby-lang.org) (Drupal data obfuscation)

If you use a MySQL (or similar) database (so clearly Drupal, WordPress and some Symfony apps) you also need:

* mysql client on the target app server(s)
* mysql 'defaults' file we can pass to prepare scripts (default location `/etc/mysql/debian.cnf`)

Example 'defaults' file:

```
[client]
host     = 127.0.0.1
user     = root
password = MYSQL_PASSWORD
```

`host` can be an IP address or a hostname/fully qualified domain name. `user` does not have to be root, but the username selected must be able to manipulate the necessary databases and create new databases and grants.

# Quickstart

Clone this repository into a location of your choice on your CI server (usually Jenkins).

Create a means to trigger the Fabric scripts (usually a "Freestyle project" in Jenkins with a trigger based on repository change).

Ensure your application is either in a `www` repository in the repository or has a link to `./www` committed to the repository and pointing at the relative application location within the repository (the scripts expect to find an app in `www`).

Ensure your application has a `config.ini` file in the repository root, which contains at least the lines necessary to direct the deployment to a server, for example:

```
[drupal8]
example-drupal=dev1.codeenigma.com
```

'drupal8' is the build type (you may choose a string), 'example-drupal' is the repo name, as used below in the call to the script and 'dev1.codeenignma.com' is the hostname of the server to deploy to. We are building more comprehensive examples of the `config.ini` file in [our example-drupal project](https://github.com/codeenigma/example-drupal/blob/8.x/config.ini).

An example trigger command, typically placed in an Execute Shell box in Jenkins, looks like this - example uses Drupal:

```
fab -f /path/to/these/scripts/drupal/fabfile.py
main:repo=myreponame,repourl=git@git.mydomain.com:myreponame.git,build=build_${BUILD_NUMBER},branch=master,buildtype=master,keepbuilds=5
```

For any given type of application, you can look at the `main()` function in `fabfile.py` in the appropriate sub-directory, in this case `./drupal/fabfile.py`.

# Known Issues

Drupal scripts are the most mature, as our specialism is as a Drupal development company, though we have WordPress and Symfony projects as well, and we also do some work with [Magento](https://magento.com).

## General

* our `_sshagent_run()` now supports a path to a private key, however some deploy scripts need updating to allow it to be passed to the `main()` function
* Nginx is the preferred web server, Apache support isn there and it mostly works, but the initial build parts for WordPress and Drupal may be shaky
* some manual manipulation of vhosts might be required if you do not like the default URL format
* we're working around some challenges with regard to supporting [AWS RDS](https://aws.amazon.com/rds/) for MySQL initial builds and initial builds in cluster environments generally

## Drupal

* the `drush status` check does not use the `--format` option, and ceased to work with Drush 9 (we'll fix this pretty quick!)
* Drupal 8 multisites are a work in progress
* need to improve support for prebuilt Drupal apps, where the 'vendor' directory exists already

## WordPress

* the scripts work well for less complex WordPress sites, but are untested on more complex implementations

## Symfony

* need to parse `parameters.yml` and allow developers to specify parameters to use for database manipulation / backups

# Roadmap

These scripts are continually improved, specific enhancements on our radar are:

* Magento support
* unit tests
* support for front-end framework compilers
* better microservice support
