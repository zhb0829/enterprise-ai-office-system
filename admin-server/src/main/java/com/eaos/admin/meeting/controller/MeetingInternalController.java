package com.eaos.admin.meeting.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.meeting.dto.MeetingProgressPayload;
import com.eaos.admin.meeting.dto.MeetingResultPayload;
import com.eaos.admin.meeting.service.MeetingTaskService;
import com.eaos.admin.meeting.support.MeetingInternalTokenVerifier;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/meeting/tasks")
@RequiredArgsConstructor
public class MeetingInternalController {

  private final MeetingTaskService taskService;
  private final MeetingInternalTokenVerifier tokenVerifier;

  @PostMapping("/{taskId}/progress")
  public R<?> progress(
      @PathVariable Long taskId,
      @Valid @RequestBody MeetingProgressPayload payload,
      HttpServletRequest request) {
    verify(request);
    taskService.updateProgress(taskId, payload);
    return R.ok();
  }

  @PostMapping("/{taskId}/result")
  public R<?> result(
      @PathVariable Long taskId,
      @RequestBody MeetingResultPayload payload,
      HttpServletRequest request) {
    verify(request);
    taskService.handleResult(taskId, payload);
    return R.ok();
  }

  @PostMapping("/{taskId}/failure")
  public R<?> failure(
      @PathVariable Long taskId,
      @RequestBody Map<String, Object> payload,
      HttpServletRequest request) {
    verify(request);
    taskService.handleFailure(taskId, String.valueOf(payload.getOrDefault("error", "整理失败")));
    return R.ok();
  }

  private void verify(HttpServletRequest request) {
    if (!tokenVerifier.verify(request)) {
      throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid internal token");
    }
  }
}
