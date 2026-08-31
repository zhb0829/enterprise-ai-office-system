package com.eaos.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("sys_password_reset")
public class SysPasswordReset {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long userId;

  private LocalDateTime resetAt;

  private LocalDateTime createdAt;
}
