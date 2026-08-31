package com.eaos.admin.notification;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.meeting.entity.UserNotification;
import com.eaos.admin.meeting.mapper.UserNotificationMapper;
import com.eaos.admin.security.SecurityUtils;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 统一站内信（消息中心）：会议/舆情告警/资质任务等模块统一经由本服务发布到 user_notification。 */
@Service
@RequiredArgsConstructor
public class NotificationService {

  private final UserNotificationMapper notificationMapper;
  private final SysUserMapper sysUserMapper;

  /** 发布单用户站内信。 */
  @Transactional
  public void publish(
      Long userId, String type, String title, String content, String refType, Long refId) {
    if (userId == null) {
      return;
    }
    UserNotification notification = new UserNotification();
    notification.setUserId(userId);
    notification.setType(type);
    notification.setTitle(title);
    notification.setContent(content);
    notification.setRefType(refType);
    notification.setRefId(refId);
    notification.setIsRead(false);
    notificationMapper.insert(notification);
  }

  /** 发布给某角色全部用户（如资质任务失败通知管理员）。 */
  @Transactional
  public void publishToRole(
      String role, String type, String title, String content, String refType, Long refId) {
    sysUserMapper
        .selectList(
            new LambdaQueryWrapper<com.eaos.admin.entity.SysUser>()
                .eq(com.eaos.admin.entity.SysUser::getRole, role)
                .eq(com.eaos.admin.entity.SysUser::getEnabled, true))
        .forEach(user -> publish(user.getId(), type, title, content, refType, refId));
  }

  public Map<String, Object> page(Long userId, String type, int page, int pageSize) {
    LambdaQueryWrapper<UserNotification> wrapper =
        Wrappers.lambdaQuery(UserNotification.class).eq(UserNotification::getUserId, userId);
    if (type != null && !type.isBlank()) {
      wrapper.eq(UserNotification::getType, type);
    }
    long total = notificationMapper.selectCount(wrapper);
    pageSize = Math.min(100, Math.max(1, pageSize));
    wrapper.orderByDesc(UserNotification::getCreatedAt);
    wrapper.last("LIMIT " + pageSize + " OFFSET " + ((Math.max(1, page) - 1) * pageSize));
    List<UserNotification> items = notificationMapper.selectList(wrapper);
    return Map.of("items", items, "total", total, "page", page, "pageSize", pageSize);
  }

  public long unreadCount(Long userId) {
    return notificationMapper.selectCount(
        Wrappers.lambdaQuery(UserNotification.class)
            .eq(UserNotification::getUserId, userId)
            .eq(UserNotification::getIsRead, false));
  }

  public void markRead(Long userId, Long id) {
    UserNotification notification = notificationMapper.selectById(id);
    if (notification == null || !notification.getUserId().equals(userId)) {
      throw new IllegalArgumentException("通知不存在");
    }
    notification.setIsRead(true);
    notificationMapper.updateById(notification);
  }

  public void markAllRead(Long userId, String type) {
    UserNotification patch = new UserNotification();
    patch.setIsRead(true);
    LambdaQueryWrapper<UserNotification> wrapper =
        Wrappers.lambdaQuery(UserNotification.class)
            .eq(UserNotification::getUserId, userId)
            .eq(UserNotification::getIsRead, false);
    if (type != null && !type.isBlank()) {
      wrapper.eq(UserNotification::getType, type);
    }
    notificationMapper.update(patch, wrapper);
  }

  public Long currentUserIdOrThrow() {
    Long userId = SecurityUtils.currentUserId();
    if (userId == null) {
      throw new IllegalArgumentException("未认证");
    }
    return userId;
  }
}
