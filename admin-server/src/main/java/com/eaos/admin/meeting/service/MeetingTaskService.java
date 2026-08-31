package com.eaos.admin.meeting.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.entity.SysUser;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.meeting.dto.MeetingProgressPayload;
import com.eaos.admin.meeting.dto.MeetingResultPayload;
import com.eaos.admin.meeting.entity.Conference;
import com.eaos.admin.meeting.entity.ConferenceMaterial;
import com.eaos.admin.meeting.entity.ConferenceMedia;
import com.eaos.admin.meeting.entity.ConferenceReport;
import com.eaos.admin.meeting.entity.ConferenceTask;
import com.eaos.admin.meeting.entity.KnowledgeCard;
import com.eaos.admin.meeting.mapper.ConferenceMapper;
import com.eaos.admin.meeting.mapper.ConferenceMaterialMapper;
import com.eaos.admin.meeting.mapper.ConferenceMediaMapper;
import com.eaos.admin.meeting.mapper.ConferenceReportMapper;
import com.eaos.admin.meeting.mapper.ConferenceTaskMapper;
import com.eaos.admin.meeting.mapper.KnowledgeCardMapper;
import com.eaos.admin.meeting.support.MeetingInternalTokenVerifier;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

/**
 * 整理任务派发与 Python 回调处理。 派发：Java → Python POST /internal/meeting/conferences/{id}/reorganize
 * 回调：Python → Java POST /internal/meeting/tasks/{taskId}/progress|result|failure
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MeetingTaskService {

  private final ConferenceTaskMapper taskMapper;
  private final ConferenceMapper conferenceMapper;
  private final ConferenceMaterialMapper materialMapper;
  private final ConferenceReportMapper reportMapper;
  private final ConferenceMediaMapper mediaMapper;
  private final KnowledgeCardMapper cardMapper;
  private final SysUserMapper userMapper;
  private final MeetingNotificationService notificationService;
  private final RestTemplate restTemplate;
  private final AiServiceProperties aiServiceProperties;

  @Value("${eaos.meeting.internal-token:eaos-meeting-internal-dev-token}")
  private String internalToken;

  /** 派发整理任务到 Python 服务（同步 HTTP 触发，异步执行）。 */
  public void dispatch(
      ConferenceTask task, Conference conference, List<ConferenceMaterial> materials) {
    String url =
        aiServiceProperties.getBaseUrl()
            + "/internal/meeting/conferences/"
            + conference.getId()
            + "/reorganize";
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    headers.set(MeetingInternalTokenVerifier.HEADER, internalToken);

    Map<String, Object> body = new LinkedHashMap<>();
    body.put("taskId", task.getId());
    body.put("conference", conferencePayload(conference));
    body.put("materials", materials.stream().map(this::materialPayload).toList());
    body.put("existingCards", latestCards(conference.getId()));

    try {
      restTemplate.postForObject(url, new HttpEntity<>(body, headers), Map.class);
      task.setStatus("running");
      task.setStartedAt(LocalDateTime.now());
      taskMapper.updateById(task);
    } catch (Exception ex) {
      log.error("会议整理任务派发失败 taskId={} conferenceId={}", task.getId(), conference.getId(), ex);
      markFailed(task, conference, "派发失败：" + ex.getMessage());
      notifyCreator(
          conference, false, "会议「" + conference.getName() + "」整理失败", "失败原因：任务无法派发到 AI 服务。");
      throw new IllegalArgumentException("整理任务派发失败：" + ex.getMessage());
    }
  }

  @Transactional
  public void updateProgress(Long taskId, MeetingProgressPayload payload) {
    ConferenceTask task = requireTask(taskId);
    task.setProgress(payload.getSteps());
    if (payload.getStatus() != null
        && List.of("running", "partial").contains(payload.getStatus())) {
      task.setStatus(payload.getStatus());
    }
    taskMapper.updateById(task);
    updateMaterials(payload.getMaterials());
  }

  @Transactional
  public void handleResult(Long taskId, MeetingResultPayload payload) {
    ConferenceTask task = requireTask(taskId);
    if ("succeeded".equals(task.getStatus())) {
      return; // 回调幂等
    }
    Conference conference = requireConference(task.getConferenceId());

    MeetingResultPayload.ReportPayload reportPayload = payload.getReport();
    if (reportPayload == null
        || reportPayload.getContent() == null
        || reportPayload.getContent().isBlank()) {
      throw new IllegalArgumentException("整理结果缺少纪要内容");
    }

    ConferenceReport report = new ConferenceReport();
    report.setConferenceId(conference.getId());
    report.setVersion(reportMapper.maxVersion(conference.getId()) + 1);
    report.setContent(reportPayload.getContent());
    report.setTriggerReason("整理任务 #" + task.getId());
    report.setGeneratedByModel(payload.getModel() == null ? "" : payload.getModel());
    report.setRelatedPolicies(
        reportPayload.getRelatedPolicies() == null
            ? List.of()
            : reportPayload.getRelatedPolicies());
    report.setRelatedConferences(
        reportPayload.getRelatedConferences() == null
            ? List.of()
            : reportPayload.getRelatedConferences());
    report.setRelatedCompetitors(
        reportPayload.getRelatedCompetitors() == null
            ? List.of()
            : reportPayload.getRelatedCompetitors());
    reportMapper.insert(report);

    if (payload.getCards() != null) {
      for (Map<String, Object> card : payload.getCards()) {
        KnowledgeCard entity = new KnowledgeCard();
        entity.setConferenceId(conference.getId());
        entity.setReportId(report.getId());
        entity.setCardType(str(card.get("cardType")));
        entity.setTitle(str(card.get("title")));
        entity.setContent(str(card.get("content")));
        entity.setActor(str(card.get("actor")));
        entity.setExpectedTime(str(card.get("expectedTime")));
        Object sourceRef = card.get("sourceRef");
        List<Map<String, Object>> refs =
            sourceRef instanceof List ? castMapList(sourceRef) : List.of();
        if (refs.isEmpty()) {
          refs = List.of(Map.of("status", "待确认", "reason", "未提供可核验来源"));
          entity.setContent("【待确认】" + entity.getContent());
        }
        entity.setSourceRef(refs);
        cardMapper.insert(entity);
      }
    }

    updateMaterials(payload.getMaterials());

    if (payload.getMedia() != null) {
      Set<String> existingUrls =
          new HashSet<>(
              mediaMapper
                  .selectList(
                      Wrappers.lambdaQuery(ConferenceMedia.class)
                          .eq(ConferenceMedia::getConferenceId, conference.getId()))
                  .stream()
                  .map(ConferenceMedia::getSourceUrl)
                  .toList());
      for (Map<String, Object> media : payload.getMedia()) {
        String url = str(media.get("sourceUrl"));
        if (!url.isEmpty() && !existingUrls.add(url)) {
          continue; // 媒体报道按 source_url 去重
        }
        ConferenceMedia entity = new ConferenceMedia();
        entity.setConferenceId(conference.getId());
        entity.setTitle(str(media.get("title")));
        entity.setSourceUrl(url);
        entity.setSourceName(str(media.get("sourceName")));
        entity.setPublishedAt(parseTime(media.get("publishedAt")));
        entity.setSummary(str(media.get("summary")));
        entity.setContentPath(str(media.get("contentPath")));
        mediaMapper.insert(entity);
      }
    }

    conference.setStatus("completed");
    conference.setLastError("");
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.updateById(conference);

    task.setStatus("succeeded");
    task.setProgress(payload.getSteps());
    task.setError("");
    task.setFinishedAt(LocalDateTime.now());
    taskMapper.updateById(task);

    notifyCreator(
        conference,
        true,
        "会议「" + conference.getName() + "」整理完成",
        "纪要 v" + report.getVersion() + " 已生成，含知识卡片与关联推荐。");
  }

  @Transactional
  public void handleFailure(Long taskId, String error) {
    ConferenceTask task = requireTask(taskId);
    if ("failed".equals(task.getStatus())) {
      return;
    }
    Conference conference = requireConference(task.getConferenceId());
    markFailed(task, conference, error == null ? "整理失败" : error);
    notifyCreator(
        conference,
        false,
        "会议「" + conference.getName() + "」整理失败",
        "失败原因：" + (error == null || error.isBlank() ? "未知错误" : error));
  }

  private void markFailed(ConferenceTask task, Conference conference, String error) {
    task.setStatus("failed");
    task.setError(error == null ? "" : error);
    task.setFinishedAt(LocalDateTime.now());
    taskMapper.updateById(task);
    conference.setStatus("draft");
    conference.setLastError(error == null ? "" : error);
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.updateById(conference);
  }

  private void notifyCreator(Conference conference, boolean success, String title, String content) {
    Long userId = resolveUserId(conference.getCreatedBy());
    if (userId == null) {
      log.warn(
          "会议创建者无法解析，通知未发送 conferenceId={} createdBy={}",
          conference.getId(),
          conference.getCreatedBy());
      return;
    }
    notificationService.notify(
        userId,
        "meeting",
        title,
        content,
        success ? "conference_completed" : "conference_failed",
        conference.getId());
  }

  private void updateMaterials(List<Map<String, Object>> materials) {
    if (materials == null) {
      return;
    }
    for (Map<String, Object> item : materials) {
      Long id = longValue(item.get("id"));
      ConferenceMaterial material = id == null ? null : materialMapper.selectById(id);
      if (material == null) {
        continue;
      }
      String status = str(item.get("parseStatus"));
      if (List.of("pending", "parsed", "failed").contains(status)) {
        material.setParseStatus(status);
      }
      Object result = item.get("parseResult");
      if (result instanceof Map<?, ?> map) {
        material.setParseResult(castMap(map));
      }
      materialMapper.updateById(material);
    }
  }

  private List<Map<String, Object>> latestCards(Long conferenceId) {
    ConferenceReport latest =
        reportMapper.selectOne(
            Wrappers.lambdaQuery(ConferenceReport.class)
                .eq(ConferenceReport::getConferenceId, conferenceId)
                .orderByDesc(ConferenceReport::getVersion)
                .last("LIMIT 1"));
    if (latest == null) {
      return List.of();
    }
    return cardMapper
        .selectList(
            Wrappers.lambdaQuery(KnowledgeCard.class)
                .eq(KnowledgeCard::getReportId, latest.getId())
                .orderByAsc(KnowledgeCard::getId))
        .stream()
        .map(
            card -> {
              Map<String, Object> item = new LinkedHashMap<>();
              item.put("cardType", card.getCardType());
              item.put("title", card.getTitle());
              item.put("content", card.getContent());
              item.put("actor", card.getActor());
              item.put("expectedTime", card.getExpectedTime());
              item.put("sourceRef", card.getSourceRef());
              return item;
            })
        .toList();
  }

  private Long resolveUserId(String username) {
    if (username == null || username.isBlank()) {
      return null;
    }
    SysUser user =
        userMapper.selectOne(
            Wrappers.lambdaQuery(SysUser.class).eq(SysUser::getUsername, username));
    return user == null ? null : user.getId();
  }

  private ConferenceTask requireTask(Long taskId) {
    ConferenceTask task = taskMapper.selectById(taskId);
    if (task == null) {
      throw new IllegalArgumentException("整理任务不存在：" + taskId);
    }
    return task;
  }

  private Conference requireConference(Long conferenceId) {
    Conference conference = conferenceMapper.selectById(conferenceId);
    if (conference == null) {
      throw new IllegalArgumentException("会议不存在：" + conferenceId);
    }
    return conference;
  }

  @SuppressWarnings("unchecked")
  private List<Map<String, Object>> castMapList(Object raw) {
    List<Map<String, Object>> result = new ArrayList<>();
    for (Object item : (List<Object>) raw) {
      if (item instanceof Map<?, ?> map) {
        result.add((Map<String, Object>) map);
      }
    }
    return result;
  }

  private Map<String, Object> castMap(Map<?, ?> raw) {
    Map<String, Object> result = new LinkedHashMap<>();
    raw.forEach((key, value) -> result.put(String.valueOf(key), value));
    return result;
  }

  private Long longValue(Object value) {
    if (value instanceof Number number) {
      return number.longValue();
    }
    try {
      return value == null ? null : Long.parseLong(String.valueOf(value));
    } catch (NumberFormatException ex) {
      return null;
    }
  }

  private String str(Object value) {
    return value == null ? "" : String.valueOf(value);
  }

  private LocalDateTime parseTime(Object value) {
    if (value == null || String.valueOf(value).isBlank()) {
      return null;
    }
    try {
      return LocalDateTime.parse(String.valueOf(value).replace(" ", "T").substring(0, 19));
    } catch (Exception ex) {
      return null;
    }
  }

  private Map<String, Object> conferencePayload(Conference conference) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("id", conference.getId());
    payload.put("name", conference.getName());
    payload.put("category", conference.getCategory());
    payload.put(
        "startTime", conference.getStartTime() == null ? "" : conference.getStartTime().toString());
    payload.put(
        "endTime", conference.getEndTime() == null ? "" : conference.getEndTime().toString());
    payload.put("location", conference.getLocation());
    payload.put("organizer", conference.getOrganizer());
    payload.put("description", conference.getDescription());
    payload.put("keywords", conference.getKeywords());
    payload.put("competitors", conference.getCompetitors());
    return payload;
  }

  private Map<String, Object> materialPayload(ConferenceMaterial material) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("id", material.getId());
    payload.put("materialType", material.getMaterialType());
    payload.put("title", material.getTitle());
    payload.put("sourceUrl", material.getSourceUrl());
    payload.put("filePath", material.getFilePath());
    payload.put("mimeType", material.getMimeType());
    payload.put("sizeBytes", material.getSizeBytes());
    payload.put("parseStatus", material.getParseStatus());
    payload.put("parseResult", material.getParseResult());
    return payload;
  }
}
