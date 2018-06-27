<?php
namespace CodeEnigma\Deployments\Robo\common;

use Robo\Task\BaseTask;
use Robo\Common\TaskIO;
use Robo\Contract\TaskInterface;

class Config extends BaseTask implements TaskInterface
{
  use TaskIO;
  public function __construct() {}
  public function run() {}

  public function returnConfigItem(
    $build_type,
    $section,
    $item,
    $default_value = null,
    $notify = true,
    $cast_value = false,
    $var_type = "string",
    $deprecate = false,
    $replacement_section = null
    ) {
      $value = \Robo\Robo::Config()->get("command.build.$build_type.$section.$item", $default_value);
      if ($value) {
        if ($deprecate) {
          if ($replacement_section) {
            $this->printTaskError("###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! Please use '$replacement_section' instead\n");
          }
          else {
            $this->printTaskError("###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! This option is being REMOVED!\n");
          }
        }
        if ($notify) {
          $this->printTaskSuccess("===> '$item' in '$section' being set to '$value'");
        }
        if ($cast_value) {
          settype($value, $var_type);
        }
      }
      return $value;
  }

}