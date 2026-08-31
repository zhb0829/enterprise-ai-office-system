package com.eaos.admin.notification;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.common.R;
import com.eaos.admin.security.SecurityUtils;
import java.time.LocalDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 通知渠道管理（管理端，仅管理员）。 */
@RestController
@RequestMapping("/api/admin/notification-channels")
@RequiredArgsConstructor
public class NotificationChannelController {

  private final NotificationChannelMapper channelMapper;

  @GetMapping
  public R<List<NotificationChannel>> list() {
    requireAdmin();
    return R.ok(
        channelMapper.selectList(
            Wrappers.lambdaQuery(NotificationChannel.class)
                .orderByDesc(NotificationChannel::getCreatedAt)));
  }

  @PostMapping
  @Transactional
  public R<NotificationChannel> create(@RequestBody NotificationChannel body) {
    requireAdmin();
    body.setId(null);
    body.setCreatedAt(LocalDateTime.now());
    body.setUpdatedAt(LocalDateTime.now());
    if (body.getEnabled() == null) {
      body.setEnabled(true);
    }
    channelMapper.insert(body);
    return R.ok(body);
  }

  @PutMapping("/{id}")
  @Transactional
  public R<Void> update(@PathVariable Long id, @RequestBody NotificationChannel body) {
    requireAdmin();
    NotificationChannel channel = channelMapper.selectById(id);
    if (channel == null) {
      throw new IllegalArgumentException("通知渠道不存在");
    }
    if (body.getName() != null) {
      channel.setName(body.getName());
    }
    if (body.getType() != null) {
      channel.setType(body.getType());
    }
    if (body.getConfig() != null) {
      channel.setConfig(body.getConfig());
    }
    if (body.getEnabled() != null) {
      channel.setEnabled(body.getEnabled());
    }
    channel.setUpdatedAt(LocalDateTime.now());
    channelMapper.updateById(channel);
    return R.ok();
  }

  @DeleteMapping("/{id}")
  @Transactional
  public R<Void> delete(@PathVariable Long id) {
    requireAdmin();
    channelMapper.deleteById(id);
    return R.ok();
  }

  private void requireAdmin() {
    if (!SecurityUtils.isAdmin()) {
      throw new IllegalArgumentException("仅系统管理员可管理通知渠道");
    }
  }
}
