<?php
namespace CodeEnigma\Deployments\Robo\common;

/**
 * Trait loadTasks
 * @package CodeEnigma\Deployments
 */
trait loadTasks {

  protected function taskConfig()
  {
    return $this->task(Config::class);
  }

  protected function taskDeployUtilsTasks()
  {
    return $this->task(DeployUtilsTasks::class);
  }

}