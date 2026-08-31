package com.eaos.admin.notification;

import com.eaos.admin.common.R;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 统一消息中心（站内信）入口：会议 / 舆情告警 / 资质任务等全部类型的站内通知。 */
@RestController
@RequestMapping("/api/notifications")
@RequiredArgsConstructor
public class NotificationController {

  private final NotificationService notificationService;

  @GetMapping
  public R<Map<String, Object>> page(
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int pageSize,
      @RequestParam(required = false) String type) {
    return R.ok(
        notificationService.page(notificationService.currentUserIdOrThrow(), type, page, pageSize));
  }

  @GetMapping("/unread-count")
  public R<Map<String, Object>> unreadCount() {
    return R.ok(
        Map.of(
            "count", notificationService.unreadCount(notificationService.currentUserIdOrThrow())));
  }

  @PostMapping("/{id}/read")
  public R<Void> markRead(@PathVariable Long id) {
    notificationService.markRead(notificationService.currentUserIdOrThrow(), id);
    return R.ok();
  }

  @PostMapping("/read-all")
  public R<Void> markAllRead(@RequestParam(required = false) String type) {
    notificationService.markAllRead(notificationService.currentUserIdOrThrow(), type);
    return R.ok();
  }
}
