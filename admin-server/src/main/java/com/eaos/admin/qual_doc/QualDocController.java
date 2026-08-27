package com.eaos.admin.qual_doc;

import com.eaos.admin.common.R;
import com.eaos.admin.security.LoginUser;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.nio.charset.StandardCharsets;

@RestController
@RequestMapping("/api/qual")
@RequiredArgsConstructor
public class QualDocController {

    private final QualDocService service;

    @PostMapping(value = "/guides/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public R<?> uploadGuide(
            @RequestParam String qualificationType,
            @RequestParam String guideName,
            @RequestParam(defaultValue = "v1") String version,
            @RequestParam(defaultValue = "") String sourceUrl,
            @RequestPart MultipartFile file,
            @AuthenticationPrincipal LoginUser user) throws Exception {
        return R.ok(service.parseAndCreateGuide(owner(user), qualificationType, guideName, version, sourceUrl, file));
    }

    @GetMapping("/guides")
    public R<?> guides(@AuthenticationPrincipal LoginUser user) {
        return R.ok(service.guides(owner(user)));
    }

    @PostMapping(value = "/materials/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public R<?> uploadMaterial(@RequestPart MultipartFile file, @AuthenticationPrincipal LoginUser user) throws Exception {
        return R.ok(service.uploadMaterial(owner(user), file));
    }

    @GetMapping("/materials")
    public R<?> materials(@AuthenticationPrincipal LoginUser user) {
        return R.ok(service.materials(owner(user)));
    }

    @PostMapping("/tasks")
    public R<?> createTask(@Valid @RequestBody QualDto.CreateTaskRequest request, @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.createTask(owner(user), request));
    }

    @GetMapping("/tasks")
    public R<?> tasks(@AuthenticationPrincipal LoginUser user) {
        return R.ok(service.tasks(owner(user)));
    }

    @GetMapping("/tasks/{taskId}")
    public R<?> task(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.task(taskId, owner(user)));
    }

    @GetMapping(value = "/tasks/{taskId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        return service.subscribe(taskId, owner(user));
    }

    @GetMapping("/tasks/{taskId}/reports")
    public R<?> reports(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.validationReports(taskId, owner(user)));
    }

    @GetMapping("/documents/{documentId}")
    public R<?> document(@PathVariable String documentId, @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.document(documentId, owner(user)));
    }

    @PostMapping("/documents/{documentId}/edit")
    public R<?> saveDocument(@PathVariable String documentId, @RequestBody QualDto.SaveDocumentRequest request,
                             @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.saveDocument(documentId, owner(user), request));
    }

    @GetMapping("/documents/{documentId}/versions")
    public R<?> versions(@PathVariable String documentId, @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.versions(documentId, owner(user)));
    }

    @PostMapping("/documents/{documentId}/review/{action}")
    public R<?> review(@PathVariable String documentId, @PathVariable String action,
                       @RequestBody(required = false) QualDto.ReviewRequest request,
                       @AuthenticationPrincipal LoginUser user) {
        return R.ok(service.review(documentId, owner(user), action, request == null ? "" : request.comment()));
    }

    @GetMapping("/documents/{documentId}/export")
    public void export(@PathVariable String documentId, @AuthenticationPrincipal LoginUser user,
                       HttpServletResponse response) {
        byte[] data = service.exportFormalDocx(documentId, owner(user));
        response.setContentType("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION,
                ContentDisposition.attachment().filename("qualification-draft.docx", StandardCharsets.UTF_8).build().toString());
        try {
            response.getOutputStream().write(data);
        } catch (Exception ex) {
            throw new IllegalStateException("文件下载失败", ex);
        }
    }

    @GetMapping("/validation-rules")
    public R<?> rules() {
        return R.ok(service.rules());
    }

    @PostMapping("/validation-rules")
    public R<?> saveRule(@Valid @RequestBody QualDto.CreateRuleRequest request) {
        return R.ok(service.saveRule(request));
    }

    private String owner(LoginUser user) {
        return user == null ? "demo-enterprise" : "enterprise-" + user.getId();
    }
}
