package com.eaos.admin.meeting.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.meeting.entity.UserNotification;
import com.eaos.admin.meeting.mapper.UserNotificationMapper;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class MeetingNotificationService {

  private final UserNotificationMapper notificationMapper;

  public void notify(
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

  public Map<String, Object> page(Long userId, int page, int pageSize) {
    LambdaQueryWrapper<UserNotification> wrapper =
        Wrappers.lambdaQuery(UserNotification.class).eq(UserNotification::getUserId, userId);
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

  public void markAllRead(Long userId) {
    UserNotification patch = new UserNotification();
    patch.setIsRead(true);
    notificationMapper.update(
        patch,
        Wrappers.lambdaQuery(UserNotification.class)
            .eq(UserNotification::getUserId, userId)
            .eq(UserNotification::getIsRead, false));
  }
}
