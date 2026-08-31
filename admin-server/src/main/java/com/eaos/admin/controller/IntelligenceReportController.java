package com.eaos.admin.controller;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.common.R;
import com.eaos.admin.entity.IntelligenceReport;
import com.eaos.admin.mapper.IntelligenceReportMapper;
import com.eaos.admin.service.IntelligenceAdminService;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reports/intelligence")
@RequiredArgsConstructor
public class IntelligenceReportController {
  private final IntelligenceReportMapper mapper;
  private final IntelligenceAdminService service;

  @GetMapping
  public R<List<IntelligenceReport>> list(@RequestParam(required = false) String period) {
    var wrapper = Wrappers.<IntelligenceReport>query().orderByDesc("generated_at");
    if (period != null && !period.isBlank()) wrapper.eq("period", period);
    return R.ok(mapper.selectList(wrapper));
  }

  @PostMapping("/generate")
  public R<Map<String, Object>> generate(@RequestBody(required = false) Map<String, String> body) {
    String period = body == null ? "daily" : body.getOrDefault("period", "daily");
    return R.ok(service.generateReport(period));
  }
}
