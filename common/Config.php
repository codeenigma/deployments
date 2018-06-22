<?php


function return_config_item(
        $buildtype,
        $section,
        $item,
        $var_type = "string",
        $default_value = null,
        $notify = true,
        $cast_value = false,
        $deprecate = false,
        $replacement_section = null
) {
  $value = \Robo\Robo::Config()->get("command.build.$buildtype.$section.$item");
  if ($item) {
    if ($deprecate) {
      if ($replacement_section) {
        print "###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! Please use '$replacement_section' instead\n";
      }
      else {
        print "###### Fetching '$item' from '$section' in your YAML config file - DEPRECATED! This option is being REMOVED!\n";
      }
    }
    if ($notify) {
      print "===> '$item' in '$section' being set to '$value'\n";
    }
    if ($cast_value) {
      settype($value, $var_type);
    }
    return $value;
  }
}