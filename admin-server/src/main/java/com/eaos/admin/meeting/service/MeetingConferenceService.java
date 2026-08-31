package com.eaos.admin.meeting.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.meeting.dto.ConferenceSaveRequest;
import com.eaos.admin.meeting.dto.MaterialLinkRequest;
import com.eaos.admin.meeting.dto.MeetingPageQuery;
import com.eaos.admin.meeting.dto.TranscriptRequest;
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
import com.eaos.admin.meeting.support.CurrentUser;
import com.eaos.admin.meeting.support.MeetingStorageService;
import com.eaos.admin.storage.FileStorage;
import java.io.IOException;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

@Service
@RequiredArgsConstructor
public class MeetingConferenceService {

  private static final int MAX_MATERIALS = 50;
  private static final long MAX_FILE_BYTES = 100L * 1024 * 1024;
  private static final long MAX_AUDIO_BYTES = 500L * 1024 * 1024;
  private static final List<String> CATEGORIES = List.of("行业会议", "论坛", "发布会", "其他");

  private final ConferenceMapper conferenceMapper;
  private final ConferenceMaterialMapper materialMapper;
  private final ConferenceReportMapper reportMapper;
  private final KnowledgeCardMapper cardMapper;
  private final ConferenceTaskMapper taskMapper;
  private final ConferenceMediaMapper mediaMapper;
  private final MeetingStorageService storageService;
  private final MeetingTaskService taskService;

  public Map<String, Object> page(MeetingPageQuery query) {
    int page = Math.max(1, query.getPage() == null ? 1 : query.getPage());
    int pageSize =
        Math.min(100, Math.max(1, query.getPageSize() == null ? 20 : query.getPageSize()));
    LambdaQueryWrapper<Conference> wrapper = Wrappers.lambdaQuery(Conference.class);
    if (query.getStatus() != null && !query.getStatus().isBlank()) {
      wrapper.eq(Conference::getStatus, query.getStatus().trim());
    }
    if (query.getArchived() != null) {
      wrapper.eq(Conference::getArchived, query.getArchived());
    } else {
      wrapper.eq(Conference::getArchived, false);
    }
    if (query.getKeyword() != null && !query.getKeyword().isBlank()) {
      String keyword = query.getKeyword().trim();
      wrapper.and(
          w ->
              w.like(Conference::getName, keyword)
                  .or()
                  .like(Conference::getOrganizer, keyword)
                  .or()
                  .like(Conference::getKeywords, keyword));
    }
    long total = conferenceMapper.selectCount(wrapper);
    wrapper
        .orderByDesc(Conference::getStartTime)
        .orderByDesc(Conference::getCreatedAt)
        .last("LIMIT " + pageSize + " OFFSET " + ((page - 1) * pageSize));
    List<Map<String, Object>> items =
        conferenceMapper.selectList(wrapper).stream().map(this::summary).toList();
    return Map.of("items", items, "total", total, "page", page, "pageSize", pageSize);
  }

  public Map<String, Object> detail(Long id) {
    Conference conference = requireConference(id);
    List<ConferenceReport> reports =
        reportMapper.selectList(
            Wrappers.lambdaQuery(ConferenceReport.class)
                .eq(ConferenceReport::getConferenceId, id)
                .orderByDesc(ConferenceReport::getVersion));
    ConferenceReport latest = reports.isEmpty() ? null : reports.getFirst();
    Map<Long, List<KnowledgeCard>> cardsByReport = new LinkedHashMap<>();
    for (ConferenceReport report : reports) {
      cardsByReport.put(
          report.getId(),
          cardMapper.selectList(
              Wrappers.lambdaQuery(KnowledgeCard.class)
                  .eq(KnowledgeCard::getReportId, report.getId())
                  .orderByAsc(KnowledgeCard::getId)));
    }
    List<KnowledgeCard> cards =
        latest == null ? List.of() : cardsByReport.getOrDefault(latest.getId(), List.of());
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("conference", conference);
    result.put(
        "materials",
        materialMapper.selectList(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, id)
                .orderByDesc(ConferenceMaterial::getCreatedAt)));
    result.put("reports", reports);
    result.put("latestReport", latest);
    result.put("cards", cards);
    result.put("cardsByReport", cardsByReport);
    result.put(
        "media",
        mediaMapper.selectList(
            Wrappers.lambdaQuery(ConferenceMedia.class)
                .eq(ConferenceMedia::getConferenceId, id)
                .orderByDesc(ConferenceMedia::getPublishedAt)
                .orderByDesc(ConferenceMedia::getCollectedAt)));
    result.put(
        "tasks",
        taskMapper.selectList(
            Wrappers.lambdaQuery(ConferenceTask.class)
                .eq(ConferenceTask::getConferenceId, id)
                .orderByDesc(ConferenceTask::getCreatedAt)));
    result.put("canManage", canManage(conference));
    return result;
  }

  public ConferenceReport report(Long conferenceId, Long reportId) {
    requireConference(conferenceId);
    ConferenceReport report = reportMapper.selectById(reportId);
    if (report == null || !conferenceId.equals(report.getConferenceId())) {
      throw new IllegalArgumentException("会议纪要版本不存在");
    }
    return report;
  }

  @Transactional
  public Conference create(ConferenceSaveRequest request) {
    requireAdminOrOpenDevelopment();
    Conference conference = new Conference();
    apply(conference, request);
    conference.setStatus("draft");
    conference.setArchived(false);
    conference.setLastError("");
    conference.setCreatedBy(CurrentUser.username().isBlank() ? "manual" : CurrentUser.username());
    conference.setCreatedAt(LocalDateTime.now());
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.insert(conference);
    return conference;
  }

  @Transactional
  public Conference update(Long id, ConferenceSaveRequest request) {
    Conference conference = requireManageable(id);
    ensureEditable(conference);
    apply(conference, request);
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.updateById(conference);
    return conference;
  }

  @Transactional
  public void delete(Long id) {
    Conference conference = requireManageable(id);
    if ("processing".equals(conference.getStatus())) {
      throw new IllegalArgumentException("整理中的会议不能删除");
    }
    List<ConferenceMaterial> materials =
        materialMapper.selectList(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, id));
    materials.forEach(material -> storageService.delete(material.getFilePath()));
    List<Long> reportIds =
        reportMapper
            .selectList(
                Wrappers.lambdaQuery(ConferenceReport.class)
                    .eq(ConferenceReport::getConferenceId, id))
            .stream()
            .map(ConferenceReport::getId)
            .toList();
    if (!reportIds.isEmpty()) {
      cardMapper.delete(
          Wrappers.lambdaQuery(KnowledgeCard.class).in(KnowledgeCard::getReportId, reportIds));
    }
    mediaMapper.delete(
        Wrappers.lambdaQuery(ConferenceMedia.class).eq(ConferenceMedia::getConferenceId, id));
    taskMapper.delete(
        Wrappers.lambdaQuery(ConferenceTask.class).eq(ConferenceTask::getConferenceId, id));
    reportMapper.delete(
        Wrappers.lambdaQuery(ConferenceReport.class).eq(ConferenceReport::getConferenceId, id));
    materialMapper.delete(
        Wrappers.lambdaQuery(ConferenceMaterial.class).eq(ConferenceMaterial::getConferenceId, id));
    conferenceMapper.deleteById(id);
  }

  @Transactional
  public Conference archive(Long id, boolean archived) {
    Conference conference = requireManageable(id);
    if ("processing".equals(conference.getStatus())) {
      throw new IllegalArgumentException("整理中的会议不能归档");
    }
    conference.setArchived(archived);
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.updateById(conference);
    return conference;
  }

  @Transactional
  public ConferenceMaterial addLink(Long conferenceId, MaterialLinkRequest request) {
    Conference conference = requireManageable(conferenceId);
    ensureEditable(conference);
    ensureMaterialCapacity(conferenceId);
    String url = request.getUrl().trim();
    if (!url.matches("^https?://.+")) {
      throw new IllegalArgumentException("资料链接仅支持 http/https");
    }
    ensureUniqueUrl(conferenceId, url);
    ConferenceMaterial material =
        baseMaterial(conferenceId, "link", blankTo(request.getTitle(), url), "text/html", 0L);
    material.setSourceUrl(url);
    materialMapper.insert(material);
    return material;
  }

  @Transactional
  public ConferenceMaterial addTranscript(Long conferenceId, TranscriptRequest request)
      throws IOException {
    Conference conference = requireManageable(conferenceId);
    ensureEditable(conference);
    ensureMaterialCapacity(conferenceId);
    byte[] bytes = request.getContent().getBytes(java.nio.charset.StandardCharsets.UTF_8);
    if (bytes.length > MAX_FILE_BYTES) {
      throw new IllegalArgumentException("转录文本不能超过 100MB");
    }
    String title = blankTo(request.getTitle(), "会议转录稿");
    String path = storageService.saveText(conferenceId, "transcript.txt", request.getContent());
    String hash = sha256(bytes);
    if (materialMapper.selectCount(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, conferenceId)
                .eq(ConferenceMaterial::getFileSha256, hash))
        > 0) {
      storageService.delete(path);
      throw new IllegalArgumentException("该转录文本已添加，请勿重复提交");
    }
    ConferenceMaterial material =
        baseMaterial(conferenceId, "transcript", title, "text/plain", (long) bytes.length);
    material.setFilePath(path);
    material.setFileSha256(hash);
    materialMapper.insert(material);
    return material;
  }

  @Transactional
  public ConferenceMaterial upload(Long conferenceId, MultipartFile file) throws IOException {
    Conference conference = requireManageable(conferenceId);
    ensureEditable(conference);
    ensureMaterialCapacity(conferenceId);
    if (file == null || file.isEmpty()) {
      throw new IllegalArgumentException("上传文件不能为空");
    }
    String mime =
        file.getContentType() == null ? "application/octet-stream" : file.getContentType();
    String type = materialType(file.getOriginalFilename(), mime);
    long limit = "audio".equals(type) ? MAX_AUDIO_BYTES : MAX_FILE_BYTES;
    if (file.getSize() > limit) {
      throw new IllegalArgumentException("audio".equals(type) ? "音频不能超过 500MB" : "单文件不能超过 100MB");
    }
    FileStorage.StoredFile stored = storageService.save(conferenceId, file);
    if (materialMapper.selectCount(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, conferenceId)
                .eq(ConferenceMaterial::getFileSha256, stored.sha256()))
        > 0) {
      storageService.delete(stored.path());
      throw new IllegalArgumentException("该文件已上传，请勿重复提交");
    }
    ConferenceMaterial material =
        baseMaterial(
            conferenceId, type, blankTo(file.getOriginalFilename(), "未命名资料"), mime, file.getSize());
    material.setFilePath(stored.path());
    material.setFileSha256(stored.sha256());
    materialMapper.insert(material);
    return material;
  }

  @Transactional
  public void deleteMaterial(Long conferenceId, Long materialId) {
    Conference conference = requireManageable(conferenceId);
    ensureEditable(conference);
    ConferenceMaterial material = materialMapper.selectById(materialId);
    if (material == null || !conferenceId.equals(material.getConferenceId())) {
      throw new IllegalArgumentException("会议资料不存在");
    }
    materialMapper.deleteById(materialId);
    storageService.delete(material.getFilePath());
  }

  public ConferenceTask organize(Long conferenceId) {
    Conference conference = requireManageable(conferenceId);
    if (Boolean.TRUE.equals(conference.getArchived())) {
      throw new IllegalArgumentException("已归档会议不能发起整理");
    }
    if ("processing".equals(conference.getStatus())) {
      throw new IllegalArgumentException("会议正在整理中");
    }
    List<ConferenceMaterial> materials = materials(conferenceId);
    if (materials.isEmpty()) {
      throw new IllegalArgumentException("请至少添加一份会议资料");
    }
    ConferenceTask task = new ConferenceTask();
    task.setConferenceId(conferenceId);
    task.setTaskType("reorganize");
    task.setStatus("pending");
    task.setProgress(initialProgress());
    task.setError("");
    task.setRetryCount(0);
    task.setCreatedAt(LocalDateTime.now());
    taskMapper.insert(task);
    markProcessing(conference);
    taskService.dispatch(task, conference, materials);
    return task;
  }

  public ConferenceTask retry(Long conferenceId, Long taskId) {
    Conference conference = requireManageable(conferenceId);
    ConferenceTask task = taskMapper.selectById(taskId);
    if (task == null
        || !conferenceId.equals(task.getConferenceId())
        || !"failed".equals(task.getStatus())) {
      throw new IllegalArgumentException("仅失败的会议整理任务可以重试");
    }
    task.setStatus("pending");
    task.setError("");
    task.setRetryCount((task.getRetryCount() == null ? 0 : task.getRetryCount()) + 1);
    task.setFinishedAt(null);
    taskMapper.updateById(task);
    markProcessing(conference);
    taskService.dispatch(task, conference, materials(conferenceId));
    return task;
  }

  private void apply(Conference conference, ConferenceSaveRequest request) {
    if (request.getEndTime() != null
        && request.getStartTime() != null
        && request.getEndTime().isBefore(request.getStartTime())) {
      throw new IllegalArgumentException("结束时间不能早于开始时间");
    }
    String category = blankTo(request.getCategory(), "行业会议");
    if (!CATEGORIES.contains(category)) {
      throw new IllegalArgumentException("不支持的会议类别");
    }
    conference.setName(request.getName().trim());
    conference.setCategory(category);
    conference.setStartTime(request.getStartTime());
    conference.setEndTime(request.getEndTime());
    conference.setLocation(trim(request.getLocation()));
    conference.setOrganizer(trim(request.getOrganizer()));
    conference.setDescription(trim(request.getDescription()));
    conference.setKeywords(trim(request.getKeywords()));
    conference.setCompetitors(trim(request.getCompetitors()));
  }

  private Map<String, Object> summary(Conference conference) {
    Map<String, Object> item = new LinkedHashMap<>();
    item.put("id", conference.getId());
    item.put("name", conference.getName());
    item.put("category", conference.getCategory());
    item.put("startTime", conference.getStartTime());
    item.put("location", conference.getLocation());
    item.put("organizer", conference.getOrganizer());
    item.put("keywords", conference.getKeywords());
    item.put("status", conference.getStatus());
    item.put("archived", conference.getArchived());
    item.put("lastError", conference.getLastError());
    item.put("createdBy", conference.getCreatedBy());
    item.put(
        "materialCount",
        materialMapper.selectCount(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, conference.getId())));
    ConferenceReport latest =
        reportMapper.selectOne(
            Wrappers.lambdaQuery(ConferenceReport.class)
                .eq(ConferenceReport::getConferenceId, conference.getId())
                .orderByDesc(ConferenceReport::getVersion)
                .last("LIMIT 1"));
    item.put("latestVersion", latest == null ? null : latest.getVersion());
    return item;
  }

  private ConferenceMaterial baseMaterial(
      Long conferenceId, String type, String title, String mime, Long size) {
    ConferenceMaterial material = new ConferenceMaterial();
    material.setConferenceId(conferenceId);
    material.setMaterialType(type);
    material.setTitle(title);
    material.setSourceUrl("");
    material.setFilePath("");
    material.setFileSha256("");
    material.setMimeType(mime);
    material.setSizeBytes(size);
    material.setParseStatus("pending");
    material.setParseResult(Map.of());
    material.setCreatedAt(LocalDateTime.now());
    return material;
  }

  private List<ConferenceMaterial> materials(Long conferenceId) {
    return materialMapper.selectList(
        Wrappers.lambdaQuery(ConferenceMaterial.class)
            .eq(ConferenceMaterial::getConferenceId, conferenceId)
            .orderByAsc(ConferenceMaterial::getId));
  }

  private void ensureUniqueUrl(Long conferenceId, String url) {
    if (materialMapper.selectCount(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, conferenceId)
                .eq(ConferenceMaterial::getSourceUrl, url))
        > 0) {
      throw new IllegalArgumentException("该资料链接已添加");
    }
  }

  private void ensureMaterialCapacity(Long conferenceId) {
    if (materialMapper.selectCount(
            Wrappers.lambdaQuery(ConferenceMaterial.class)
                .eq(ConferenceMaterial::getConferenceId, conferenceId))
        >= MAX_MATERIALS) {
      throw new IllegalArgumentException("单个会议最多添加 50 份资料");
    }
  }

  private void ensureEditable(Conference conference) {
    if (Boolean.TRUE.equals(conference.getArchived())) {
      throw new IllegalArgumentException("已归档会议只读");
    }
    if ("processing".equals(conference.getStatus())) {
      throw new IllegalArgumentException("整理中的会议暂不可修改资料");
    }
  }

  private Conference requireManageable(Long id) {
    Conference conference = requireConference(id);
    if (!canManage(conference)) {
      throw new IllegalArgumentException("仅会议创建者或管理员可执行该操作");
    }
    return conference;
  }

  private boolean canManage(Conference conference) {
    return CurrentUser.isAdmin() || CurrentUser.username().equals(conference.getCreatedBy());
  }

  private void requireAdminOrOpenDevelopment() {
    if (!CurrentUser.isAdmin()) {
      throw new IllegalArgumentException("仅管理员可录入公开会议");
    }
  }

  private Conference requireConference(Long id) {
    Conference conference = conferenceMapper.selectById(id);
    if (conference == null) {
      throw new IllegalArgumentException("会议不存在");
    }
    return conference;
  }

  private void markProcessing(Conference conference) {
    conference.setStatus("processing");
    conference.setLastError("");
    conference.setUpdatedAt(LocalDateTime.now());
    conferenceMapper.updateById(conference);
  }

  private List<Map<String, Object>> initialProgress() {
    return List.of(
        step("collect", "采集补充报道"),
        step("parse", "解析多模态资料"),
        step("extract", "提炼会议要点"),
        step("generate", "生成纪要与知识卡片"),
        step("recommend", "关联政策、竞品与历史会议"));
  }

  private Map<String, Object> step(String step, String label) {
    return Map.of("step", step, "label", label, "status", "pending");
  }

  private String materialType(String filename, String mime) {
    String value = (filename == null ? "" : filename).toLowerCase(Locale.ROOT);
    if (mime.startsWith("image/")) {
      return "image";
    }
    if (mime.startsWith("audio/") || value.matches(".*\\.(mp3|wav|m4a|aac|ogg|flac)$")) {
      return "audio";
    }
    return "file";
  }

  private String sha256(byte[] bytes) {
    try {
      return java.util.HexFormat.of()
          .formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (java.security.NoSuchAlgorithmException ex) {
      throw new IllegalStateException("运行环境不支持 SHA-256", ex);
    }
  }

  private String blankTo(String value, String fallback) {
    return value == null || value.isBlank() ? fallback : value.trim();
  }

  private String trim(String value) {
    return value == null ? "" : value.trim();
  }
}
