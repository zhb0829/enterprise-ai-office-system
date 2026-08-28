package com.eaos.admin.qual_doc;

import com.eaos.admin.config.AiServiceProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

@Slf4j
@Service
@RequiredArgsConstructor
public class QualDocService {

    private static final String PROTOCOL_VERSION = "1.0";
    private static final String SYSTEM_OWNER = "system";

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final QualStateMachineService stateMachine;
    private final QualStorageService storageService;
    private final RestTemplate restTemplate;
    private final AiServiceProperties aiProperties;

    @Value("${eaos.qual.citation-min-score:0.72}")
    private double citationMinScore;

    private final Map<String, CopyOnWriteArrayList<SseEmitter>> taskEmitters = new ConcurrentHashMap<>();

    @Transactional
    public Map<String, Object> parseAndCreateGuide(String owner, String qualificationType, String guideName,
                                                    String version, String sourceUrl, MultipartFile file) throws IOException {
        String path = storageService.save("guides/" + owner, file);
        Map<String, Object> parsed = callParser("/internal/qual/parse-guide", file);
        String id = id();
        Map<String, Object> schema = map(parsed.get("schema"));
        List<Map<String, Object>> checklist = maps(parsed.get("materialChecklist"));
        jdbc.update("""
                        UPDATE qual_guide_schema SET status = 'ARCHIVED', effective_to = CURRENT_DATE, updated_at = NOW()
                        WHERE owner_enterprise_id = ? AND qualification_type = ? AND status = 'ACTIVE'
                        """, owner, qualificationType);
        jdbc.update("""
                        INSERT INTO qual_guide_schema(id, owner_enterprise_id, qualification_type, guide_name, version,
                          source_file_name, source_file_path, source_url, schema_json, material_checklist_json, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, 'ACTIVE')
                        """,
                id, owner, qualificationType, guideName, blankOr(version, "v1"), safeFileName(file), path, blank(sourceUrl),
                json(schema), json(checklist));
        return guide(id, owner);
    }

    public Map<String, Object> uploadMaterial(String owner, MultipartFile file) throws IOException {
        String path = storageService.save("materials/" + owner, file);
        Map<String, Object> parsed = callParser("/internal/qual/parse-material", file);
        String id = id();
        String content = String.valueOf(parsed.getOrDefault("text", "")).trim();
        if (content.isBlank()) {
            throw new IllegalArgumentException("未从企业资料中提取到可用文本");
        }
        jdbc.update("""
                        INSERT INTO qual_material(id, owner_enterprise_id, category, file_name, file_path, text_content, parse_status)
                        VALUES (?, ?, 'QUALIFICATION_ARCHIVE', ?, ?, ?, 'READY')
                        """, id, owner, safeFileName(file), path, content);
        return material(id, owner, false);
    }

    @Transactional
    public Map<String, Object> createTask(String owner, QualDto.CreateTaskRequest request) {
        Map<String, Object> guide = guide(request.guideSchemaId(), owner);
        if (!"ACTIVE".equals(guide.get("status"))) {
            throw new IllegalStateException("仅可使用已生效的资质指南版本");
        }
        String idem = blankOr(request.idempotencyKey(), UUID.randomUUID().toString());
        List<Map<String, Object>> existing = jdbc.queryForList(
                "SELECT id FROM qual_task WHERE owner_enterprise_id = ? AND idempotency_key = ?", owner, idem);
        if (!existing.isEmpty()) {
            return task(String.valueOf(existing.getFirst().get("id")), owner);
        }
        List<String> requestedMaterialIds = request.materialIds() == null ? List.of() : request.materialIds();
        List<String> materialIds = requestedMaterialIds.stream().filter(id -> materialExists(id, owner)).toList();
        if (materialIds.size() != requestedMaterialIds.size()) {
            throw new IllegalArgumentException("所选企业资料不存在或不属于当前企业");
        }
        String taskId = id();
        jdbc.update("""
                        INSERT INTO qual_task(id, owner_enterprise_id, qualification_type, guide_schema_id, document_type,
                          status, idempotency_key, material_ids_json, format_requirements_json)
                        VALUES (?, ?, ?, ?, ?, 'CREATED', ?, ?::jsonb, ?::jsonb)
                        """, taskId, owner, request.qualificationType(), request.guideSchemaId(), request.documentType(), idem,
                json(materialIds), json(orEmpty(request.formatRequirements())));
        changeTaskStatus(taskId, owner, QualTaskStatus.PARSING, 5, "已锁定指南版本，等待 Worker 处理");
        scheduleWorkerAfterCommit(taskId, owner);
        return task(taskId, owner);
    }

    public List<Map<String, Object>> tasks(String owner) {
        return jdbc.queryForList("SELECT id FROM qual_task WHERE owner_enterprise_id = ? AND status <> 'ARCHIVED' ORDER BY created_at DESC", owner)
                .stream().map(row -> task(String.valueOf(row.get("id")), owner)).toList();
    }

    private static final String TASK_QUERY = """
            SELECT t.*, g.guide_name, g.version AS guide_version, d.id AS document_id, d.status AS document_status
            FROM qual_task t JOIN qual_guide_schema g ON g.id = t.guide_schema_id
            LEFT JOIN qual_document d ON d.task_id = t.id
            """;

    public Map<String, Object> task(String taskId, String owner) {
        List<Map<String, Object>> rows = jdbc.queryForList(TASK_QUERY + " WHERE t.id = ? AND t.owner_enterprise_id = ?", taskId, owner);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质任务不存在或无访问权限");
        }
        return taskMap(rows.getFirst());
    }

    public Map<String, Object> adminTask(String taskId) {
        List<Map<String, Object>> rows = jdbc.queryForList(TASK_QUERY + " WHERE t.id = ?", taskId);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质任务不存在");
        }
        return taskMap(rows.getFirst());
    }

    private Map<String, Object> taskMap(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("ownerEnterpriseId", row.get("owner_enterprise_id"));
        out.put("qualificationType", row.get("qualification_type"));
        out.put("guideSchemaId", row.get("guide_schema_id"));
        out.put("guideName", row.get("guide_name"));
        out.put("guideVersion", row.get("guide_version"));
        out.put("documentType", row.get("document_type"));
        out.put("status", row.get("status"));
        out.put("progress", number(row.get("progress")));
        out.put("progressMessage", row.get("progress_message"));
        out.put("materialIds", list(row.get("material_ids_json")));
        out.put("formatRequirements", map(row.get("format_requirements_json")));
        out.put("failureReason", row.get("failure_reason"));
        out.put("preArchiveStatus", row.get("pre_archive_status"));
        out.put("documentId", row.get("document_id"));
        out.put("documentStatus", row.get("document_status"));
        out.put("createdAt", row.get("created_at"));
        out.put("updatedAt", row.get("updated_at"));
        return out;
    }

    public List<Map<String, Object>> guides(String owner) {
        return jdbc.queryForList("SELECT id FROM qual_guide_schema WHERE owner_enterprise_id = ? ORDER BY created_at DESC", owner)
                .stream().map(row -> guide(String.valueOf(row.get("id")), owner)).toList();
    }

    public Map<String, Object> guide(String guideId, String owner) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM qual_guide_schema WHERE id = ? AND owner_enterprise_id = ?", guideId, owner);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质指南不存在或无访问权限");
        }
        Map<String, Object> row = rows.getFirst();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("qualificationType", row.get("qualification_type"));
        out.put("guideName", row.get("guide_name"));
        out.put("version", row.get("version"));
        out.put("effectiveFrom", row.get("effective_from"));
        out.put("effectiveTo", row.get("effective_to"));
        out.put("sourceFileName", row.get("source_file_name"));
        out.put("sourceUrl", row.get("source_url"));
        out.put("schema", map(row.get("schema_json")));
        out.put("materialChecklist", maps(row.get("material_checklist_json")));
        out.put("status", row.get("status"));
        out.put("createdAt", row.get("created_at"));
        return out;
    }

    public List<Map<String, Object>> materials(String owner) {
        return jdbc.queryForList("SELECT id FROM qual_material WHERE owner_enterprise_id = ? AND category = 'QUALIFICATION_ARCHIVE' ORDER BY created_at DESC", owner)
                .stream().map(row -> material(String.valueOf(row.get("id")), owner, false)).toList();
    }

    private Map<String, Object> material(String materialId, String owner, boolean includeText) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM qual_material WHERE id = ? AND owner_enterprise_id = ?", materialId, owner);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质档案不存在或无访问权限");
        }
        Map<String, Object> row = rows.getFirst();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("fileName", row.get("file_name"));
        out.put("category", row.get("category"));
        out.put("parseStatus", row.get("parse_status"));
        out.put("textLength", String.valueOf(row.get("text_content")).length());
        out.put("createdAt", row.get("created_at"));
        if (includeText) {
            out.put("text", row.get("text_content"));
        }
        return out;
    }

    @Transactional
    public Map<String, Object> saveDocument(String documentId, String owner, QualDto.SaveDocumentRequest request, String createdBy) {
        Map<String, Object> document = document(documentId, owner);
        QualDocumentStatus status = QualDocumentStatus.valueOf(String.valueOf(document.get("status")));
        if (status == QualDocumentStatus.LOCKED) {
            throw new IllegalStateException("归档版本不可编辑");
        }
        Map<String, Object> before = map(document.get("content"));
        Map<String, Object> after = orEmpty(request.content());
        List<Map<String, Object>> diff = blockDiff(before, after);
        String note = blank(request.changeNote());
        if (note.isBlank()) {
            note = diffSummary(diff);
        }
        int nextVersion = number(document.get("currentVersion")) + 1;
        jdbc.update("UPDATE qual_document SET content_json = ?::jsonb, current_version = ?, updated_at = NOW() WHERE id = ?",
                json(after), nextVersion, documentId);
        insertVersion(documentId, owner, nextVersion, after, diff, note, createdBy);
        return document(documentId, owner);
    }

    @Transactional
    public Map<String, Object> rollbackDocument(String documentId, String owner, Integer versionNo, String createdBy) {
        if (versionNo == null || versionNo < 1) {
            throw new IllegalArgumentException("目标版本号无效");
        }
        Map<String, Object> document = document(documentId, owner);
        QualDocumentStatus status = QualDocumentStatus.valueOf(String.valueOf(document.get("status")));
        if (status == QualDocumentStatus.LOCKED) {
            throw new IllegalStateException("归档版本不可回滚");
        }
        List<Map<String, Object>> found = jdbc.queryForList(
                "SELECT content_json FROM qual_document_version WHERE document_id = ? AND owner_enterprise_id = ? AND version_no = ?",
                documentId, owner, versionNo);
        if (found.isEmpty()) {
            throw new IllegalArgumentException("目标版本不存在");
        }
        Map<String, Object> before = map(document.get("content"));
        Map<String, Object> after = map(found.getFirst().get("content_json"));
        List<Map<String, Object>> diff = blockDiff(before, after);
        int nextVersion = number(document.get("currentVersion")) + 1;
        jdbc.update("UPDATE qual_document SET content_json = ?::jsonb, current_version = ?, updated_at = NOW() WHERE id = ?",
                json(after), nextVersion, documentId);
        insertVersion(documentId, owner, nextVersion, after, diff, "回滚至 v" + versionNo, createdBy);
        return document(documentId, owner);
    }

    public Map<String, Object> document(String documentId, String owner) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM qual_document WHERE id = ? AND owner_enterprise_id = ?", documentId, owner);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质文档不存在或无访问权限");
        }
        Map<String, Object> row = rows.getFirst();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("taskId", row.get("task_id"));
        out.put("title", row.get("title"));
        out.put("status", row.get("status"));
        out.put("content", map(row.get("content_json")));
        out.put("sources", maps(row.get("sources_json")));
        out.put("riskFlags", strings(row.get("risk_flags_json")));
        out.put("currentVersion", number(row.get("current_version")));
        out.put("reviewComment", row.get("review_comment"));
        out.put("generatedAt", row.get("generated_at"));
        out.put("model", row.get("model"));
        out.put("createdAt", row.get("created_at"));
        return out;
    }

    public List<Map<String, Object>> versions(String documentId, String owner) {
        document(documentId, owner);
        return jdbc.queryForList("SELECT * FROM qual_document_version WHERE document_id = ? AND owner_enterprise_id = ? ORDER BY version_no DESC", documentId, owner)
                .stream().map(row -> Map.<String, Object>of(
                        "id", row.get("id"), "version", row.get("version_no"), "content", map(row.get("content_json")),
                        "diff", maps(row.get("diff_json")), "changeNote", row.get("change_note"), "createdBy", row.get("created_by"), "createdAt", row.get("created_at")))
                .toList();
    }

    @Transactional
    public byte[] exportFormalDocx(String documentId, String owner, String createdBy) {
        Map<String, Object> document = document(documentId, owner);
        QualDocumentStatus status = QualDocumentStatus.valueOf(String.valueOf(document.get("status")));
        if (status != QualDocumentStatus.APPROVED && status != QualDocumentStatus.DRAFT) {
            throw new IllegalStateException("文档当前状态不允许导出");
        }
        snapshotForEvent(documentId, owner, "导出归档自动快照", createdBy);
        stateMachine.assertDocumentTransition(status, QualDocumentStatus.LOCKED);
        try (XWPFDocument docx = new XWPFDocument(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            XWPFParagraph title = docx.createParagraph();
            title.setStyle("Title");
            title.createRun().setText(String.valueOf(document.get("title")));
            for (Map<String, Object> section : maps(map(document.get("content")).get("sections"))) {
                XWPFParagraph heading = docx.createParagraph();
                heading.setStyle("Heading1");
                heading.createRun().setText(String.valueOf(section.getOrDefault("title", "未命名章节")));
                for (Map<String, Object> block : maps(section.get("blocks"))) {
                    if ("table".equals(block.get("type"))) {
                        continue;
                    }
                    XWPFParagraph paragraph = docx.createParagraph();
                    paragraph.createRun().setText(String.valueOf(block.getOrDefault("text", "")));
                }
            }
            docx.write(out);
            stateMachine.assertDocumentTransition(status, QualDocumentStatus.LOCKED);
            jdbc.update("UPDATE qual_document SET status = 'LOCKED', updated_at = NOW() WHERE id = ?", documentId);
            return out.toByteArray();
        } catch (IOException ex) {
            throw new IllegalStateException("生成 DOCX 失败", ex);
        }
    }

    public List<Map<String, Object>> validationReports(String taskId, String owner) {
        task(taskId, owner);
        return jdbc.queryForList("SELECT * FROM qual_validation_report WHERE task_id = ? AND owner_enterprise_id = ? ORDER BY created_at DESC", taskId, owner)
                .stream().map(row -> Map.<String, Object>of("id", row.get("id"), "summary", map(row.get("summary_json")),
                        "items", maps(row.get("items_json")), "createdAt", row.get("created_at"))).toList();
    }

    public List<Map<String, Object>> enterprises() {
        return jdbc.queryForList("SELECT id, username, nickname FROM sys_user ORDER BY id").stream().map(row -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("id", row.get("id"));
            out.put("username", row.get("username"));
            out.put("nickname", Objects.toString(row.get("nickname"), ""));
            out.put("ownerKey", "enterprise-" + row.get("id"));
            return out;
        }).toList();
    }

    public List<Map<String, Object>> adminTasks(String owner, String status) {
        List<String> conditions = new ArrayList<>();
        List<Object> args = new ArrayList<>();
        if (owner != null && !owner.isBlank()) {
            conditions.add("t.owner_enterprise_id = ?");
            args.add(owner.trim());
        }
        if (status != null && !status.isBlank()) {
            conditions.add("t.status = ?");
            args.add(status.trim());
        }
        String sql = TASK_QUERY + (conditions.isEmpty() ? "" : " WHERE " + String.join(" AND ", conditions)) + " ORDER BY t.created_at DESC";
        Map<String, String> names = enterpriseNames();
        return jdbc.queryForList(sql, args.toArray()).stream()
                .map(row -> {
                    Map<String, Object> out = taskMap(row);
                    String ownerKey = String.valueOf(out.get("ownerEnterpriseId"));
                    out.put("ownerName", names.getOrDefault(ownerKey, ownerKey));
                    return out;
                }).toList();
    }

    public List<Map<String, Object>> adminOwnerMaterials(String owner) {
        return jdbc.queryForList("SELECT id FROM qual_material WHERE owner_enterprise_id = ? AND category = 'QUALIFICATION_ARCHIVE' ORDER BY created_at DESC", owner)
                .stream().map(row -> material(String.valueOf(row.get("id")), owner, false)).toList();
    }

    public Map<String, Object> adminTaskDetail(String taskId) {
        Map<String, Object> task = adminTask(taskId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("task", task);
        Object documentId = task.get("documentId");
        if (documentId != null) {
            String owner = String.valueOf(task.get("ownerEnterpriseId"));
            out.put("document", document(String.valueOf(documentId), owner));
            out.put("reports", validationReports(taskId, owner));
            out.put("versions", versions(String.valueOf(documentId), owner));
        }
        return out;
    }

    @Transactional
    public Map<String, Object> archiveTask(String taskId) {
        Map<String, Object> task = adminTask(taskId);
        QualTaskStatus current = QualTaskStatus.valueOf(String.valueOf(task.get("status")));
        if (current != QualTaskStatus.CREATED && current != QualTaskStatus.READY_REVIEW && current != QualTaskStatus.FAILED) {
            throw new IllegalStateException("仅 CREATED、READY_REVIEW、FAILED 状态的任务可归档");
        }
        String owner = String.valueOf(task.get("ownerEnterpriseId"));
        jdbc.update("UPDATE qual_task SET pre_archive_status = ? WHERE id = ?", current.name(), taskId);
        changeTaskStatus(taskId, owner, QualTaskStatus.ARCHIVED, number(task.get("progress")), "管理员已归档该任务");
        return adminTask(taskId);
    }

    @Transactional
    public Map<String, Object> restoreTask(String taskId) {
        Map<String, Object> task = adminTask(taskId);
        if (!QualTaskStatus.ARCHIVED.name().equals(String.valueOf(task.get("status")))) {
            throw new IllegalStateException("仅 ARCHIVED 任务可恢复");
        }
        QualTaskStatus target;
        try {
            target = QualTaskStatus.valueOf(String.valueOf(task.get("preArchiveStatus")));
        } catch (IllegalArgumentException ex) {
            target = null;
        }
        if (target != QualTaskStatus.CREATED && target != QualTaskStatus.READY_REVIEW && target != QualTaskStatus.FAILED) {
            target = QualTaskStatus.FAILED;
        }
        String owner = String.valueOf(task.get("ownerEnterpriseId"));
        jdbc.update("UPDATE qual_task SET pre_archive_status = '' WHERE id = ?", taskId);
        changeTaskStatus(taskId, owner, target, number(task.get("progress")), "管理员已恢复该任务");
        return adminTask(taskId);
    }

    @Transactional
    public Map<String, Object> adminUpdateTask(String taskId, QualDto.AdminTaskUpdateRequest request) {
        Map<String, Object> task = adminTask(taskId);
        if (!QualTaskStatus.FAILED.name().equals(String.valueOf(task.get("status")))) {
            throw new IllegalStateException("仅 FAILED 任务可编辑，请先重试或归档");
        }
        String owner = String.valueOf(task.get("ownerEnterpriseId"));
        String documentType = blank(request.documentType());
        if (!documentType.isBlank()) {
            jdbc.update("UPDATE qual_task SET document_type = ? WHERE id = ?", documentType, taskId);
        }
        if (request.materialIds() != null) {
            List<String> requestedMaterialIds = request.materialIds();
            List<String> materialIds = requestedMaterialIds.stream().filter(id -> materialExists(id, owner)).toList();
            if (materialIds.size() != requestedMaterialIds.size()) {
                throw new IllegalArgumentException("所选企业资料不存在或不属于该企业");
            }
            jdbc.update("UPDATE qual_task SET material_ids_json = ?::jsonb WHERE id = ?", json(materialIds), taskId);
        }
        if (request.maxChars() != null) {
            Map<String, Object> requirements = new LinkedHashMap<>(map(task.get("formatRequirements")));
            if (request.maxChars() > 0) {
                requirements.put("maxChars", request.maxChars());
            } else {
                requirements.remove("maxChars");
            }
            jdbc.update("UPDATE qual_task SET format_requirements_json = ?::jsonb WHERE id = ?", json(requirements), taskId);
        }
        return adminTask(taskId);
    }

    @Transactional
    public Map<String, Object> retryTask(String taskId) {
        Map<String, Object> task = adminTask(taskId);
        if (!QualTaskStatus.FAILED.name().equals(String.valueOf(task.get("status")))) {
            throw new IllegalStateException("仅 FAILED 任务可重试");
        }
        String owner = String.valueOf(task.get("ownerEnterpriseId"));
        jdbc.update("UPDATE qual_task SET failure_reason = '' WHERE id = ?", taskId);
        changeTaskStatus(taskId, owner, QualTaskStatus.PARSING, 5, "管理员已触发重试，等待 Worker 处理");
        scheduleWorkerAfterCommit(taskId, owner);
        return adminTask(taskId);
    }

    @Transactional
    public Map<String, Object> unlockDocument(String documentId, String createdBy) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM qual_document WHERE id = ?", documentId);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("资质文档不存在");
        }
        Map<String, Object> row = rows.getFirst();
        QualDocumentStatus status = QualDocumentStatus.valueOf(String.valueOf(row.get("status")));
        if (status != QualDocumentStatus.LOCKED) {
            throw new IllegalStateException("仅 LOCKED 文档可解锁");
        }
        stateMachine.assertDocumentTransition(status, QualDocumentStatus.APPROVED);
        snapshotForEvent(documentId, String.valueOf(row.get("owner_enterprise_id")), "管理员解锁自动快照", createdBy);
        jdbc.update("UPDATE qual_document SET status = 'APPROVED', review_comment = ?, updated_at = NOW() WHERE id = ?",
                "管理员解锁，视为人工放行", documentId);
        return document(documentId, String.valueOf(row.get("owner_enterprise_id")));
    }

    private Map<String, String> enterpriseNames() {
        Map<String, String> names = new LinkedHashMap<>();
        for (Map<String, Object> row : jdbc.queryForList("SELECT id, username, nickname FROM sys_user")) {
            String key = "enterprise-" + row.get("id");
            String nickname = Objects.toString(row.get("nickname"), "").trim();
            names.put(key, nickname.isEmpty() ? Objects.toString(row.get("username"), key) : nickname);
        }
        return names;
    }

    public List<Map<String, Object>> rules() {
        ensureRules();
        return jdbc.queryForList("SELECT * FROM qual_validation_rule WHERE owner_enterprise_id = ? ORDER BY code", SYSTEM_OWNER)
                .stream().map(row -> Map.<String, Object>of("id", row.get("id"), "code", row.get("code"), "name", row.get("name"),
                        "ruleType", row.get("rule_type"), "rule", map(row.get("rule_json")), "enabled", row.get("enabled"))).toList();
    }

    public Map<String, Object> saveRule(QualDto.CreateRuleRequest request) {
        ensureRules();
        String existing = jdbc.query("SELECT id FROM qual_validation_rule WHERE owner_enterprise_id = ? AND code = ?", rs -> rs.next() ? rs.getString(1) : null, SYSTEM_OWNER, request.code());
        String ruleId = existing == null ? id() : existing;
        if (existing == null) {
            jdbc.update("INSERT INTO qual_validation_rule(id, owner_enterprise_id, code, name, rule_type, rule_json, enabled) VALUES (?, ?, ?, ?, ?, ?::jsonb, ?)",
                    ruleId, SYSTEM_OWNER, request.code(), request.name(), request.ruleType(), json(orEmpty(request.rule())), !Boolean.FALSE.equals(request.enabled()));
        } else {
            jdbc.update("UPDATE qual_validation_rule SET name = ?, rule_type = ?, rule_json = ?::jsonb, enabled = ?, updated_at = NOW() WHERE id = ?",
                    request.name(), request.ruleType(), json(orEmpty(request.rule())), !Boolean.FALSE.equals(request.enabled()), ruleId);
        }
        return rules().stream().filter(rule -> ruleId.equals(rule.get("id"))).findFirst().orElseThrow();
    }

    public SseEmitter subscribe(String taskId, String owner) {
        task(taskId, owner);
        SseEmitter emitter = new SseEmitter(0L);
        taskEmitters.computeIfAbsent(taskId, key -> new CopyOnWriteArrayList<>()).add(emitter);
        emitter.onCompletion(() -> removeEmitter(taskId, emitter));
        emitter.onTimeout(() -> removeEmitter(taskId, emitter));
        List<Map<String, Object>> events = jdbc.queryForList("SELECT event_type, payload_json FROM qual_task_event WHERE task_id = ? AND owner_enterprise_id = ? ORDER BY id", taskId, owner);
        try {
            for (Map<String, Object> event : events) {
                emitter.send(SseEmitter.event().name(String.valueOf(event.get("event_type"))).data(map(event.get("payload_json"))));
            }
        } catch (IOException ex) {
            removeEmitter(taskId, emitter);
        }
        return emitter;
    }

    @Transactional
    public void internalProgress(QualDto.InternalProgress progress) {
        requireProtocol(progress.protocolVersion());
        Map<String, Object> task = internalTask(progress.taskId(), progress.idempotencyKey());
        QualTaskStatus desired = switch (progress.phase().toUpperCase()) {
            case "PARSING" -> QualTaskStatus.PARSING;
            case "GENERATING" -> QualTaskStatus.GENERATING;
            case "VALIDATING" -> QualTaskStatus.VALIDATING;
            default -> throw new IllegalArgumentException("未知 Worker 阶段");
        };
        changeTaskStatus(progress.taskId(), String.valueOf(task.get("owner_enterprise_id")), desired,
                progress.progress() == null ? number(task.get("progress")) : progress.progress(),
                blankOr(progress.message(), progress.chapterIndex() == null ? "处理中" : "正在生成第 " + progress.chapterIndex() + "/" + progress.chapterTotal() + " 章节"));
    }

    @Transactional
    public void internalResult(QualDto.InternalResult result) {
        requireProtocol(result.protocolVersion());
        Map<String, Object> task = internalTask(result.taskId(), result.idempotencyKey());
        String owner = String.valueOf(task.get("owner_enterprise_id"));
        Map<String, Object> payload = orEmpty(result.document());
        String documentId = upsertWorkerDocument(result.taskId(), owner, payload, result.sources(), result.riskFlags(), result.generatedAt(), result.model(), "complete".equals(result.status()));
        if ("partial".equals(result.status())) {
            emit(result.taskId(), owner, "partial", Map.of("documentId", documentId, "status", "partial", "progress", number(task.get("progress"))));
            return;
        }
        if (!"complete".equals(result.status())) {
            throw new IllegalArgumentException("Worker 结果状态必须为 partial 或 complete");
        }
        moveTaskTo(result.taskId(), owner, QualTaskStatus.GENERATING, 85, "已收到带引用的材料初稿");
        changeTaskStatus(result.taskId(), owner, QualTaskStatus.VALIDATING, 90, "正在执行格式与引用校验");
        runValidation(result.taskId(), documentId, owner);
        jdbc.update("UPDATE qual_document SET status = 'APPROVED', review_comment = ?, updated_at = NOW() WHERE id = ?",
                "自动校验通过，免人工审核", documentId);
        emit(result.taskId(), owner, "document", Map.of("documentId", documentId, "status", "APPROVED"));
        changeTaskStatus(result.taskId(), owner, QualTaskStatus.READY_REVIEW, 100, "初稿已生成并通过校验，可直接导出正式 DOCX");
    }

    @Transactional
    public void internalFailure(QualDto.InternalFailure failure) {
        requireProtocol(failure.protocolVersion());
        Map<String, Object> task = internalTask(failure.taskId(), failure.idempotencyKey());
        String owner = String.valueOf(task.get("owner_enterprise_id"));
        QualTaskStatus current = QualTaskStatus.valueOf(String.valueOf(task.get("status")));
        if (current != QualTaskStatus.FAILED) {
            stateMachine.assertTaskTransition(current, QualTaskStatus.FAILED);
            jdbc.update("UPDATE qual_task SET status = 'FAILED', failure_reason = ?, progress_message = ?, updated_at = NOW() WHERE id = ?",
                    failure.message(), "生成未完成：" + failure.message(), failure.taskId());
        }
        emit(failure.taskId(), owner, "failed", Map.of("status", "FAILED", "message", failure.message()));
    }

    private void scheduleWorkerAfterCommit(String taskId, String owner) {
        Runnable worker = () -> launchWorker(taskId, owner);
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    java.util.concurrent.CompletableFuture.runAsync(worker);
                }
            });
        } else {
            java.util.concurrent.CompletableFuture.runAsync(worker);
        }
    }

    private void launchWorker(String taskId, String owner) {
        Map<String, Object> task = task(taskId, owner);
        Map<String, Object> guide = guide(String.valueOf(task.get("guideSchemaId")), owner);
        List<Map<String, Object>> sourceMaterials = ((List<?>) task.get("materialIds")).stream()
                .map(materialId -> material(String.valueOf(materialId), owner, true)).toList();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("protocolVersion", PROTOCOL_VERSION);
        payload.put("taskId", taskId);
        payload.put("idempotencyKey", jdbc.queryForObject("SELECT idempotency_key FROM qual_task WHERE id = ?", String.class, taskId));
        payload.put("qualificationType", task.get("qualificationType"));
        payload.put("documentType", task.get("documentType"));
        payload.put("guide", guide);
        payload.put("materials", sourceMaterials);
        payload.put("formatRequirements", task.get("formatRequirements"));
        try {
            restTemplate.postForEntity(aiProperties.getBaseUrl() + "/internal/qual/tasks/start", internalEntity(payload), Map.class);
        } catch (Exception ex) {
            log.warn("资质 Worker 不可用: {}", ex.getMessage());
            internalFailure(new QualDto.InternalFailure(PROTOCOL_VERSION, taskId, String.valueOf(payload.get("idempotencyKey")), "AI Worker 不可用，解析和校验功能仍可使用；请恢复模型服务后重试。"));
        }
    }

    private Map<String, Object> callParser(String path, MultipartFile file) {
        ByteArrayResource resource = new ByteArrayResource(bytes(file)) {
            @Override
            public String getFilename() {
                return safeFileName(file);
            }
        };
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", resource);
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(aiProperties.getBaseUrl() + path,
                    new HttpEntity<>(body, internalHeaders(MediaType.MULTIPART_FORM_DATA)), Map.class);
            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                throw new IllegalStateException("解析服务未返回有效结果");
            }
            return response.getBody();
        } catch (Exception ex) {
            throw new IllegalStateException("指南/企业资料解析失败，请确认 AI Worker 可用且文件为原生文字版 PDF、Word 或文本。", ex);
        }
    }

    private byte[] bytes(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException ex) {
            throw new IllegalArgumentException("读取上传文件失败", ex);
        }
    }

    private HttpEntity<Map<String, Object>> internalEntity(Map<String, Object> payload) {
        return new HttpEntity<>(payload, internalHeaders(MediaType.APPLICATION_JSON));
    }

    private HttpHeaders internalHeaders(MediaType type) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(type);
        headers.set("X-Internal-Token", aiProperties.getInternalToken());
        return headers;
    }

    private void runValidation(String taskId, String documentId, String owner) {
        ensureRules();
        Map<String, Object> document = document(documentId, owner);
        Map<String, Object> task = task(taskId, owner);
        Map<String, Object> guide = guide(String.valueOf(task.get("guideSchemaId")), owner);
        Map<String, Object> content = map(document.get("content"));
        String text = flattenedText(content);
        List<Map<String, Object>> items = new ArrayList<>();
        Set<String> sourceIds = maps(document.get("sources")).stream()
                .map(source -> String.valueOf(source.getOrDefault("id", "")))
                .filter(value -> !value.isBlank())
                .collect(java.util.stream.Collectors.toSet());
        for (Map<String, Object> rule : rules()) {
            if (!Boolean.TRUE.equals(rule.get("enabled"))) {
                continue;
            }
            Map<String, Object> config = map(rule.get("rule"));
            switch (String.valueOf(rule.get("ruleType"))) {
                case "NO_PLACEHOLDER" -> addCheck(items, !text.contains("{{") && !text.contains("待补充"), rule.get("code"), "文档不应含未填充占位符");
                case "MAX_CHARS" -> {
                    int max = number(config.getOrDefault("max", map(task.get("formatRequirements")).getOrDefault("maxChars", 0)));
                    if (max > 0) addCheck(items, text.length() <= max, rule.get("code"), "正文长度 " + text.length() + "/" + max);
                }
                case "CITATION_REQUIRED" -> addCheck(items, !maps(document.get("sources")).isEmpty(), rule.get("code"), "每段内容必须有可追溯引用锚点");
                default -> { }
            }
        }
        for (Map<String, Object> section : maps(content.get("sections"))) {
            for (Map<String, Object> block : maps(section.get("blocks"))) {
                if (!"text".equals(block.getOrDefault("type", "text"))) continue;
                List<Map<String, Object>> citations = maps(block.get("citations"));
                boolean valid = !citations.isEmpty() && citations.stream()
                        .map(citation -> String.valueOf(citation.getOrDefault("id", "")))
                        .allMatch(sourceIds::contains);
                addCheck(items, valid, "BLOCK_CITATION_REQUIRED", "正文内容块必须引用已登记的官方指南或企业档案来源");
            }
        }
        for (Map<String, Object> section : maps(map(guide.get("schema")).get("sections"))) {
            String name = String.valueOf(section.getOrDefault("title", section.getOrDefault("name", "")));
            if (!name.isBlank()) addCheck(items, text.contains(name) || sectionPresent(content, name), "SECTION_REQUIRED", "应包含章节：" + name);
        }
        Collection<?> materialIds = list(task.get("materialIds"));
        String filenames = materialIds.stream().map(id -> material(String.valueOf(id), owner, false).get("fileName")).map(String::valueOf).reduce("", (a, b) -> a + " " + b);
        for (Map<String, Object> material : maps(guide.get("materialChecklist"))) {
            String name = String.valueOf(material.getOrDefault("name", material.getOrDefault("materialName", ""))).trim();
            if (!name.isBlank()) addCheck(items, filenames.contains(name) || Boolean.TRUE.equals(material.get("optional")), "MATERIAL_CHECKLIST", "材料清单：" + name);
        }
        for (Map<String, Object> source : maps(document.get("sources"))) {
            double score = decimal(source.get("score"));
            addCheck(items, score >= citationMinScore, "CITATION_SCORE", "引用 " + source.getOrDefault("docTitle", source.getOrDefault("id", "未知来源")) + " 相似度 " + score);
        }
        long failures = items.stream().filter(item -> "FAIL".equals(item.get("status"))).count();
        Map<String, Object> summary = Map.of("passed", failures == 0, "total", items.size(), "failed", failures,
                "notice", "校验报告仅辅助核对，不替代正式申报核对。");
        jdbc.update("INSERT INTO qual_validation_report(id, task_id, document_id, owner_enterprise_id, summary_json, items_json) VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb)",
                id(), taskId, documentId, owner, json(summary), json(items));
    }

    private void addCheck(List<Map<String, Object>> items, boolean pass, Object code, String message) {
        items.add(Map.of("code", String.valueOf(code), "status", pass ? "PASS" : "FAIL", "message", message));
    }

    private boolean sectionPresent(Map<String, Object> content, String name) {
        return maps(content.get("sections")).stream().anyMatch(section -> name.equals(section.get("title")) || name.equals(section.get("name")));
    }

    private String upsertWorkerDocument(String taskId, String owner, Map<String, Object> content, List<Map<String, Object>> sources,
                                        List<String> riskFlags, String generatedAt, String model, boolean complete) {
        List<Map<String, Object>> found = jdbc.queryForList("SELECT id, current_version FROM qual_document WHERE task_id = ?", taskId);
        String documentId;
        if (found.isEmpty()) {
            documentId = id();
            jdbc.update("""
                            INSERT INTO qual_document(id, task_id, owner_enterprise_id, title, content_json, sources_json, risk_flags_json, generated_at, model)
                            VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?::jsonb, NOW(), ?)
                            """, documentId, taskId, owner, String.valueOf(content.getOrDefault("title", "资质申报材料初稿")), json(content), json(orEmptyList(sources)), json(orEmptyList(riskFlags)), blank(model));
            jdbc.update("INSERT INTO qual_document_version(id, document_id, owner_enterprise_id, version_no, content_json, diff_json, change_note) VALUES (?, ?, ?, 1, ?::jsonb, '[]'::jsonb, 'Worker 初稿')",
                    id(), documentId, owner, json(content));
        } else {
            documentId = String.valueOf(found.getFirst().get("id"));
            jdbc.update("UPDATE qual_document SET content_json = ?::jsonb, sources_json = ?::jsonb, risk_flags_json = ?::jsonb, generated_at = NOW(), model = ?, updated_at = NOW() WHERE id = ?",
                    json(content), json(orEmptyList(sources)), json(orEmptyList(riskFlags)), blank(model), documentId);
        }
        if (complete) emit(taskId, owner, "document", Map.of("documentId", documentId, "status", "complete"));
        return documentId;
    }

    private String documentTaskType(String documentId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT t.document_type FROM qual_task t JOIN qual_document d ON d.task_id = t.id WHERE d.id = ?", documentId);
        return rows.isEmpty() ? "" : String.valueOf(rows.getFirst().get("document_type"));
    }

    private void moveTaskTo(String taskId, String owner, QualTaskStatus target, int progress, String message) {
        Map<String, Object> raw = internalTask(taskId, jdbc.queryForObject("SELECT idempotency_key FROM qual_task WHERE id = ?", String.class, taskId));
        QualTaskStatus current = QualTaskStatus.valueOf(String.valueOf(raw.get("status")));
        if (current == target) {
            return;
        }
        if (current == QualTaskStatus.PARSING && target == QualTaskStatus.GENERATING) {
            changeTaskStatus(taskId, owner, target, progress, message);
            return;
        }
        stateMachine.assertTaskTransition(current, target);
        changeTaskStatus(taskId, owner, target, progress, message);
    }

    private void changeTaskStatus(String taskId, String owner, QualTaskStatus target, int progress, String message) {
        Map<String, Object> raw = jdbc.queryForMap("SELECT status FROM qual_task WHERE id = ? AND owner_enterprise_id = ?", taskId, owner);
        QualTaskStatus current = QualTaskStatus.valueOf(String.valueOf(raw.get("status")));
        stateMachine.assertTaskTransition(current, target);
        jdbc.update("UPDATE qual_task SET status = ?, progress = ?, progress_message = ?, updated_at = NOW() WHERE id = ?",
                target.name(), Math.max(0, Math.min(100, progress)), blank(message), taskId);
        emit(taskId, owner, "progress", Map.of("status", target.name(), "progress", Math.max(0, Math.min(100, progress)), "message", blank(message)));
    }

    private Map<String, Object> internalTask(String taskId, String idem) {
        List<Map<String, Object>> tasks = jdbc.queryForList("SELECT * FROM qual_task WHERE id = ? AND idempotency_key = ?", taskId, idem);
        if (tasks.isEmpty()) {
            throw new IllegalArgumentException("任务不存在或幂等键不匹配");
        }
        return tasks.getFirst();
    }

    private void emit(String taskId, String owner, String type, Map<String, Object> payload) {
        jdbc.update("INSERT INTO qual_task_event(task_id, owner_enterprise_id, event_type, payload_json) VALUES (?, ?, ?, ?::jsonb)", taskId, owner, type, json(payload));
        for (SseEmitter emitter : taskEmitters.getOrDefault(taskId, new CopyOnWriteArrayList<>())) {
            try {
                emitter.send(SseEmitter.event().name(type).data(payload));
            } catch (IOException ex) {
                removeEmitter(taskId, emitter);
            }
        }
    }

    private void removeEmitter(String taskId, SseEmitter emitter) {
        List<SseEmitter> emitters = taskEmitters.get(taskId);
        if (emitters != null) emitters.remove(emitter);
    }

    private void ensureRules() {
        addRuleIfMissing("NO_PLACEHOLDER", "未填充占位符", "NO_PLACEHOLDER", Map.of());
        addRuleIfMissing("MAX_CHARS", "字数上限", "MAX_CHARS", Map.of());
        addRuleIfMissing("CITATION_REQUIRED", "引用锚点必填", "CITATION_REQUIRED", Map.of());
    }

    private void addRuleIfMissing(String code, String name, String type, Map<String, Object> config) {
        Integer exists = jdbc.queryForObject("SELECT COUNT(1) FROM qual_validation_rule WHERE owner_enterprise_id = ? AND code = ?", Integer.class, SYSTEM_OWNER, code);
        if (exists != null && exists == 0) {
            jdbc.update("INSERT INTO qual_validation_rule(id, owner_enterprise_id, code, name, rule_type, rule_json, enabled) VALUES (?, ?, ?, ?, ?, ?::jsonb, TRUE)",
                    id(), SYSTEM_OWNER, code, name, type, json(config));
        }
    }

    private List<Map<String, Object>> blockDiff(Map<String, Object> before, Map<String, Object> after) {
        List<Map<String, Object>> result = new ArrayList<>();
        List<Map<String, Object>> beforeSections = maps(before.get("sections"));
        List<Map<String, Object>> afterSections = maps(after.get("sections"));
        int count = Math.max(beforeSections.size(), afterSections.size());
        for (int i = 0; i < count; i++) {
            Map<String, Object> beforeSection = i < beforeSections.size() ? beforeSections.get(i) : null;
            Map<String, Object> afterSection = i < afterSections.size() ? afterSections.get(i) : null;
            List<String> beforeTexts = blockTexts(beforeSection);
            List<String> afterTexts = blockTexts(afterSection);
            List<Map<String, Object>> changes = new ArrayList<>();
            int pairs = Math.min(beforeTexts.size(), afterTexts.size());
            for (int j = 0; j < pairs; j++) {
                if (!beforeTexts.get(j).equals(afterTexts.get(j))) {
                    Map<String, Object> change = new LinkedHashMap<>();
                    change.put("op", "modified");
                    change.put("index", j);
                    change.put("text", beforeTexts.get(j));
                    change.put("newText", afterTexts.get(j));
                    changes.add(change);
                }
            }
            for (int j = pairs; j < beforeTexts.size(); j++) {
                changes.add(Map.of("op", "removed", "index", j, "text", beforeTexts.get(j)));
            }
            for (int j = pairs; j < afterTexts.size(); j++) {
                changes.add(Map.of("op", "added", "index", j, "text", afterTexts.get(j)));
            }
            if (!changes.isEmpty()) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("section", sectionTitle(afterSection != null ? afterSection : beforeSection, i));
                entry.put("sectionIndex", i);
                entry.put("changes", changes);
                result.add(entry);
            }
        }
        return result;
    }

    private List<String> blockTexts(Map<String, Object> section) {
        if (section == null) return List.of();
        return maps(section.get("blocks")).stream()
                .filter(block -> !"table".equals(block.get("type")))
                .map(block -> String.valueOf(block.getOrDefault("text", "")))
                .toList();
    }

    private String sectionTitle(Map<String, Object> section, int index) {
        if (section == null) return "未命名章节";
        String title = String.valueOf(section.getOrDefault("title", section.getOrDefault("name", ""))).trim();
        return title.isEmpty() ? "第 " + (index + 1) + " 章节" : title;
    }

    private String diffSummary(List<Map<String, Object>> diff) {
        int modified = 0;
        int added = 0;
        int removed = 0;
        for (Map<String, Object> entry : diff) {
            for (Map<String, Object> change : maps(entry.get("changes"))) {
                switch (String.valueOf(change.get("op"))) {
                    case "modified" -> modified++;
                    case "added" -> added++;
                    case "removed" -> removed++;
                    default -> { }
                }
            }
        }
        if (modified == 0 && added == 0 && removed == 0) {
            return "无内容变更";
        }
        List<String> parts = new ArrayList<>();
        if (modified > 0) parts.add("修改 " + modified + " 段");
        if (added > 0) parts.add("新增 " + added + " 段");
        if (removed > 0) parts.add("删除 " + removed + " 段");
        return String.join("、", parts);
    }

    private void insertVersion(String documentId, String owner, int versionNo, Map<String, Object> content,
                               List<Map<String, Object>> diff, String note, String createdBy) {
        jdbc.update("""
                        INSERT INTO qual_document_version(id, document_id, owner_enterprise_id, version_no, content_json, diff_json, change_note, created_by)
                        VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?)
                        """, id(), documentId, owner, versionNo, json(content), json(diff), note, blankOr(createdBy, "manual"));
    }

    private void snapshotForEvent(String documentId, String owner, String note, String createdBy) {
        Map<String, Object> document = document(documentId, owner);
        Map<String, Object> content = map(document.get("content"));
        List<Map<String, Object>> latest = jdbc.queryForList(
                "SELECT content_json FROM qual_document_version WHERE document_id = ? AND owner_enterprise_id = ? ORDER BY version_no DESC LIMIT 1",
                documentId, owner);
        List<Map<String, Object>> diff = latest.isEmpty()
                ? new ArrayList<>()
                : blockDiff(map(latest.getFirst().get("content_json")), content);
        int nextVersion = number(document.get("currentVersion")) + 1;
        insertVersion(documentId, owner, nextVersion, content, diff, note, createdBy);
        jdbc.update("UPDATE qual_document SET current_version = ?, updated_at = NOW() WHERE id = ?", nextVersion, documentId);
    }

    private String flattenedText(Map<String, Object> content) {
        StringBuilder out = new StringBuilder();
        for (Map<String, Object> section : maps(content.get("sections"))) {
            out.append(section.getOrDefault("title", "")).append('\n');
            for (Map<String, Object> block : maps(section.get("blocks"))) out.append(block.getOrDefault("text", "")).append('\n');
        }
        return out.toString();
    }

    private void requireProtocol(String protocol) {
        if (!PROTOCOL_VERSION.equals(protocol)) throw new IllegalArgumentException("不支持的内部协议版本");
    }

    private boolean materialExists(String id, String owner) {
        Integer count = jdbc.queryForObject("SELECT COUNT(1) FROM qual_material WHERE id = ? AND owner_enterprise_id = ?", Integer.class, id, owner);
        return count != null && count > 0;
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of() : value);
        } catch (Exception ex) {
            throw new IllegalArgumentException("JSON 序列化失败", ex);
        }
    }

    private Map<String, Object> map(Object value) {
        if (value instanceof Map<?, ?> input) {
            return objectMapper.convertValue(input, new TypeReference<>() { });
        }
        if (value == null || String.valueOf(value).isBlank()) return new LinkedHashMap<>();
        try {
            return objectMapper.readValue(String.valueOf(value), new TypeReference<>() { });
        } catch (Exception ex) {
            return new LinkedHashMap<>();
        }
    }

    private List<Map<String, Object>> maps(Object value) {
        if (value == null) return List.of();
        try {
            if (value instanceof List<?> input) return input.stream().map(this::map).toList();
            return objectMapper.readValue(String.valueOf(value), new TypeReference<>() { });
        } catch (Exception ex) {
            return List.of();
        }
    }

    private List<String> strings(Object value) {
        if (value == null) return List.of();
        try {
            if (value instanceof List<?> input) return input.stream().map(String::valueOf).toList();
            return objectMapper.readValue(String.valueOf(value), new TypeReference<>() { });
        } catch (Exception ex) {
            return List.of();
        }
    }

    private List<?> list(Object value) {
        if (value instanceof List<?> list) return list;
        try {
            return objectMapper.readValue(String.valueOf(value), new TypeReference<List<Object>>() { });
        } catch (Exception ex) {
            return List.of();
        }
    }

    private Map<String, Object> orEmpty(Map<String, Object> value) { return value == null ? Map.of() : value; }
    private <T> List<T> orEmptyList(List<T> value) { return value == null ? List.of() : value; }
    private String id() { return UUID.randomUUID().toString(); }
    private String blank(String value) { return value == null ? "" : value.trim(); }
    private String blankOr(String value, String fallback) { String text = blank(value); return text.isBlank() ? fallback : text; }
    private String safeFileName(MultipartFile file) { return blankOr(file.getOriginalFilename(), "upload").replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_"); }
    private int number(Object value) { if (value instanceof Number number) return number.intValue(); try { return Integer.parseInt(String.valueOf(value)); } catch (Exception ignored) { return 0; } }
    private double decimal(Object value) { if (value instanceof Number number) return number.doubleValue(); try { return Double.parseDouble(String.valueOf(value)); } catch (Exception ignored) { return 0D; } }
}
