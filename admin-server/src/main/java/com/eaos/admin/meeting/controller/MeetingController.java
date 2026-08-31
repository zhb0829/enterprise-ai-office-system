package com.eaos.admin.meeting.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.meeting.dto.ConferenceSaveRequest;
import com.eaos.admin.meeting.dto.MaterialLinkRequest;
import com.eaos.admin.meeting.dto.MeetingPageQuery;
import com.eaos.admin.meeting.dto.TranscriptRequest;
import com.eaos.admin.meeting.entity.ConferenceReport;
import com.eaos.admin.meeting.service.MeetingConferenceService;
import com.eaos.admin.meeting.service.MeetingExportService;
import com.eaos.admin.meeting.service.MeetingNotificationService;
import com.eaos.admin.meeting.support.CurrentUser;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.util.Map;

@RestController
@RequestMapping("/api/meeting")
@RequiredArgsConstructor
public class MeetingController {

    private final MeetingConferenceService conferenceService;
    private final MeetingNotificationService notificationService;
    private final MeetingExportService exportService;

    @GetMapping("/conferences")
    public R<?> conferences(MeetingPageQuery query) {
        return R.ok(conferenceService.page(query));
    }

    @GetMapping("/conferences/{id}")
    public R<?> detail(@PathVariable Long id) {
        return R.ok(conferenceService.detail(id));
    }

    @PostMapping("/conferences")
    public R<?> create(@Valid @RequestBody ConferenceSaveRequest request) {
        return R.ok(conferenceService.create(request));
    }

    @PutMapping("/conferences/{id}")
    public R<?> update(@PathVariable Long id, @Valid @RequestBody ConferenceSaveRequest request) {
        return R.ok(conferenceService.update(id, request));
    }

    @DeleteMapping("/conferences/{id}")
    public R<?> delete(@PathVariable Long id) {
        conferenceService.delete(id);
        return R.ok();
    }

    @PostMapping("/conferences/{id}/archive")
    public R<?> archive(@PathVariable Long id, @RequestParam(defaultValue = "true") boolean archived) {
        return R.ok(conferenceService.archive(id, archived));
    }

    @PostMapping("/conferences/{id}/materials/link")
    public R<?> addLink(@PathVariable Long id, @Valid @RequestBody MaterialLinkRequest request) {
        return R.ok(conferenceService.addLink(id, request));
    }

    @PostMapping("/conferences/{id}/materials/transcript")
    public R<?> addTranscript(@PathVariable Long id, @Valid @RequestBody TranscriptRequest request) throws Exception {
        return R.ok(conferenceService.addTranscript(id, request));
    }

    @PostMapping(value = "/conferences/{id}/materials/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public R<?> upload(@PathVariable Long id, @RequestPart MultipartFile file) throws Exception {
        return R.ok(conferenceService.upload(id, file));
    }

    @DeleteMapping("/conferences/{id}/materials/{materialId}")
    public R<?> deleteMaterial(@PathVariable Long id, @PathVariable Long materialId) {
        conferenceService.deleteMaterial(id, materialId);
        return R.ok();
    }

    @PostMapping("/conferences/{id}/organize")
    public R<?> organize(@PathVariable Long id) {
        return R.ok(conferenceService.organize(id));
    }

    @PostMapping("/conferences/{id}/tasks/{taskId}/retry")
    public R<?> retry(@PathVariable Long id, @PathVariable Long taskId) {
        return R.ok(conferenceService.retry(id, taskId));
    }

    @GetMapping("/conferences/{id}/reports/{reportId}/export")
    public void export(@PathVariable Long id, @PathVariable Long reportId, HttpServletResponse response) {
        Map<String, Object> detail = conferenceService.detail(id);
        ConferenceReport report = conferenceService.report(id, reportId);
        String conferenceName = String.valueOf(((com.eaos.admin.meeting.entity.Conference)
                detail.get("conference")).getName());
        byte[] data = exportService.exportReportDocx(report, conferenceName);
        response.setContentType("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(conferenceName + "-会议纪要-v" + report.getVersion() + ".docx", StandardCharsets.UTF_8)
                .build().toString());
        try {
            response.getOutputStream().write(data);
        } catch (Exception ex) {
            throw new IllegalStateException("文件下载失败", ex);
        }
    }

    @GetMapping("/notifications")
    public R<?> notifications(@RequestParam(defaultValue = "1") int page,
                              @RequestParam(defaultValue = "20") int pageSize) {
        return R.ok(notificationService.page(currentUserId(), page, pageSize));
    }

    @GetMapping("/notifications/unread-count")
    public R<?> unreadCount() {
        return R.ok(Map.of("count", notificationService.unreadCount(currentUserId())));
    }

    @PostMapping("/notifications/{id}/read")
    public R<?> markRead(@PathVariable Long id) {
        notificationService.markRead(currentUserId(), id);
        return R.ok();
    }

    @PostMapping("/notifications/read-all")
    public R<?> markAllRead() {
        notificationService.markAllRead(currentUserId());
        return R.ok();
    }

    private Long currentUserId() {
        return CurrentUser.id() == null ? 1L : CurrentUser.id();
    }
}
