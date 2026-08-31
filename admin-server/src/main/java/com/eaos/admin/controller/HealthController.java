package com.eaos.admin.controller;

import com.eaos.admin.common.R;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class HealthController {

  @GetMapping("/health")
  public R<Map<String, Object>> health() {
    return R.ok(
        Map.of(
            "service", "admin-server",
            "status", "UP"));
  }
}
