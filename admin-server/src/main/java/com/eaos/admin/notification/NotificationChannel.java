package com.eaos.admin.notification;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("sys_notification_channel")
public class NotificationChannel {

  @TableId(type = IdType.AUTO)
  private Long id;

  private String name;

  /** webhook / email */
  private String type;

  private String config;

  private Boolean enabled;

  private LocalDateTime createdAt;

  private LocalDateTime updatedAt;
}
