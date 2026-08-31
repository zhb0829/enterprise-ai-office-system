package com.eaos.admin.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.dto.SourceConfigRequest;
import com.eaos.admin.entity.CollectionTaskLog;
import com.eaos.admin.entity.SourceConfig;
import com.eaos.admin.mapper.CollectionTaskLogMapper;
import com.eaos.admin.mapper.SourceConfigMapper;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
@RequiredArgsConstructor
public class IntelligenceAdminService {
  private final SourceConfigMapper sourceConfigMapper;
  private final CollectionTaskLogMapper taskLogMapper;
  private final RestTemplate restTemplate;
  private final AiServiceProperties aiProperties;

  public List<SourceConfig> listSources() {
    return sourceConfigMapper.selectList(Wrappers.<SourceConfig>query().orderByDesc("id"));
  }

  public SourceConfig saveSource(Long id, SourceConfigRequest request) {
    SourceConfig source = id == null ? new SourceConfig() : sourceConfigMapper.selectById(id);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    String url = request.getUrl().trim();
    var duplicateUrlQuery = Wrappers.<SourceConfig>query().eq("url", url);
    if (id != null) duplicateUrlQuery.ne("id", id);
    if (sourceConfigMapper.selectCount(duplicateUrlQuery) > 0) {
      throw new IllegalArgumentException("该采集来源 URL 已存在，请直接使用或修改现有来源");
    }

    source.setName(request.getName().trim());
    source.setType(request.getType());
    source.setUrl(url);
    source.setKeywords(request.getKeywords());
    source.setCompetitors(request.getCompetitors());
    source.setFrequency(request.getFrequency());
    source.setStatus(request.getStatus());
    if (source.getHealthStatus() == null) source.setHealthStatus("unknown");
    if (id == null) sourceConfigMapper.insert(source);
    else sourceConfigMapper.updateById(source);
    return sourceConfigMapper.selectById(source.getId());
  }

  public void deleteSource(Long id) {
    if (sourceConfigMapper.deleteById(id) == 0) throw new IllegalArgumentException("采集源不存在");
  }

  public SourceConfig toggle(Long id) {
    SourceConfig source = sourceConfigMapper.selectById(id);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    source.setStatus("enabled".equalsIgnoreCase(source.getStatus()) ? "paused" : "enabled");
    sourceConfigMapper.updateById(source);
    return sourceConfigMapper.selectById(id);
  }

  public Map<String, Object> trigger(Long sourceId) {
    String url = aiProperties.getBaseUrl() + "/internal/intelligence/sources/" + sourceId + "/run";
    return restTemplate.postForObject(url, null, Map.class);
  }

  public Map<String, Object> retry(Long taskId) {
    String url = aiProperties.getBaseUrl() + "/internal/intelligence/tasks/" + taskId + "/retry";
    return restTemplate.postForObject(url, null, Map.class);
  }

  public Map<String, Object> generateReport(String period) {
    String url =
        aiProperties.getBaseUrl() + "/internal/intelligence/reports/generate?period=" + period;
    return restTemplate.postForObject(url, null, Map.class);
  }

  public List<CollectionTaskLog> listTasks(String status, Long sourceId) {
    var wrapper = Wrappers.<CollectionTaskLog>query().orderByDesc("created_at");
    if (status != null && !status.isBlank()) wrapper.eq("status", status);
    if (sourceId != null) wrapper.eq("source_id", sourceId);
    return taskLogMapper.selectList(wrapper);
  }
}
