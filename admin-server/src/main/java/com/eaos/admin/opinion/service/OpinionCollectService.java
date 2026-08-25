package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.entity.OpinionSource;
import com.eaos.admin.opinion.entity.OpinionSourceTask;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.mapper.OpinionSourceMapper;
import com.eaos.admin.opinion.mapper.OpinionSourceTaskMapper;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionAccessService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionCollectService {

    private final OpinionSourceMapper sourceMapper;
    private final OpinionSourceTaskMapper sourceTaskMapper;
    private final OpinionMonitorMapper monitorMapper;
    private final RestTemplate restTemplate;
    private final AiServiceProperties aiServiceProperties;
    private final OpinionServiceProperties opinionProperties;
    private final OpinionAuditService auditService;
    private final OpinionAccessService accessService;

    /** 触发单个采集源采集。*/
    public OpinionSourceTask triggerSource(Long sourceId, Long monitorId) {
        OpinionSource source = sourceMapper.selectById(sourceId);
        if (source == null) {
            throw new IllegalArgumentException("采集源不存在");
        }
        if (!"approved".equals(source.getAuditStatus())) {
            throw new IllegalArgumentException("采集源未通过审核，无法采集");
        }
        if (!"enabled".equals(source.getStatus())) {
            throw new IllegalArgumentException("采集源已停用，请先启用");
        }
        OpinionSourceTask task = new OpinionSourceTask();
        task.setSourceId(sourceId);
        task.setMonitorId(monitorId);
        task.setTaskType("collect");
        task.setStatus("queued");
        sourceTaskMapper.insert(task);

        Map<String, Object> result = dispatch(source, task.getId(), monitorId);
        return sourceTaskMapper.selectById(task.getId());
    }

    /** 触发某监控任务下所有已审核启用的采集源。返回创建的任务列表。 */
    public List<OpinionSourceTask> triggerMonitor(Long monitorId) {
        OpinionMonitor monitor = monitorMapper.selectById(monitorId);
        if (monitor == null) {
            throw new IllegalArgumentException("监控任务不存在");
        }
        accessService.requireMonitor(monitorId);
        List<OpinionSource> sources = sourceMapper.selectList(Wrappers.<OpinionSource>lambdaQuery()
                .eq(OpinionSource::getAuditStatus, "approved")
                .eq(OpinionSource::getStatus, "enabled")
                .orderByDesc(OpinionSource::getPriority));
        List<OpinionSourceTask> tasks = new java.util.ArrayList<>();
        for (OpinionSource source : sources) {
            try {
                tasks.add(triggerSource(source.getId(), monitorId));
            } catch (Exception e) {
                log.warn("触发采集失败 sourceId={}: {}", source.getId(), e.getMessage());
            }
        }
        auditService.record("COLLECT_TRIGGER", "opinion_monitor", monitorId,
                Map.of("sourceCount", (long) sources.size(), "taskCount", (long) tasks.size()), null);
        return tasks;
    }

    /** 派发给 Python 采集器执行。Python 侧异步处理后会回调本服务入库接口。 */
    public Map<String, Object> dispatch(OpinionSource source, Long sourceTaskId, Long monitorId) {
        String base = aiServiceProperties.getBaseUrl();
        String url = base + "/internal/opinion/sources/" + source.getId() + "/collect";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set(InternalTokenVerifier.HEADER, sharedToken());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("sourceTaskId", sourceTaskId);
        body.put("monitorId", monitorId);
        body.put("source", sourcePayload(source));
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
        try {
            Object raw = restTemplate.postForObject(url, entity, Map.class);
            log.info("采集派发成功 sourceId={} sourceTaskId={}: {}", source.getId(), sourceTaskId, raw);
            return raw == null ? Map.of() : cast(raw);
        } catch (Exception e) {
            log.error("采集派发失败 sourceId={} sourceTaskId={}", source.getId(), sourceTaskId, e);
            OpinionSourceTask task = sourceTaskMapper.selectById(sourceTaskId);
            if (task != null) {
                task.setStatus("failed");
                task.setError(e.getMessage() == null ? "派发失败" : e.getMessage());
                task.setFinishedAt(LocalDateTime.now());
                sourceTaskMapper.updateById(task);
            }
            throw new IllegalArgumentException("采集派发失败：" + e.getMessage());
        }
    }

    public List<OpinionSourceTask> listTasks(Long monitorId, String status) {
        var wrapper = Wrappers.<OpinionSourceTask>lambdaQuery();
        if (monitorId != null) {
            accessService.requireMonitor(monitorId);
            wrapper.eq(OpinionSourceTask::getMonitorId, monitorId);
        } else if (com.eaos.admin.opinion.support.OpinionCurrentUser.isAuthenticated()
                && !com.eaos.admin.opinion.support.OpinionCurrentUser.isAdmin()) {
            var ids = accessService.visibleMonitorIds();
            if (ids.isEmpty()) {
                return List.of();
            }
            wrapper.in(OpinionSourceTask::getMonitorId, ids);
        }
        if (status != null && !status.isBlank()) {
            wrapper.eq(OpinionSourceTask::getStatus, status);
        }
        return sourceTaskMapper.selectList(wrapper.orderByDesc(OpinionSourceTask::getCreatedAt));
    }

    private Map<String, Object> sourcePayload(OpinionSource source) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("id", source.getId());
        payload.put("name", source.getName());
        payload.put("sourceType", source.getSourceType());
        payload.put("platform", source.getPlatform());
        payload.put("homepage", source.getHomepage());
        payload.put("collectMethod", source.getCollectMethod());
        payload.put("frequency", source.getFrequency());
        payload.put("rateLimit", source.getRateLimit());
        payload.put("priority", source.getPriority());
        payload.put("adapterVersion", source.getAdapterVersion());
        return payload;
    }

    private String sharedToken() {
        return opinionProperties.getInternalToken();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> cast(Object value) {
        return value instanceof Map ? (Map<String, Object>) value : Map.of();
    }
}
