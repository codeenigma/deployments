<?php
namespace CodeEnigma\Deployments\Robo\common;

/**
 * Trait loadTasks
 * @package CodeEnigma\Deployments
 */
trait loadTasks {

  protected function taskConfigTasks()
  {
    return $this->task(ConfigTasks::class);
  }

  protected function taskUtils()
  {
    return $this->task(Utils::class);
  }

  protected function taskServerTasks()
  {
    return $this->task(ServerTasks::class);
  }

}