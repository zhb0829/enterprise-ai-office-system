package com.eaos.admin.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.service.AiService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ai")
@RequiredArgsConstructor
public class AiController {

  private final AiService aiService;

  /** 网关转发示例：Java 统一入口 -> Python agent 服务内网接口 */
  @GetMapping("/health")
  public R<String> aiHealth() {
    return R.ok(aiService.health());
  }
}
