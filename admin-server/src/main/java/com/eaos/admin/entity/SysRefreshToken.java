package com.eaos.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

/** 刷新令牌：仅存 SHA-256 哈希，可吊销。 */
@Data
@TableName("sys_refresh_token")
public class SysRefreshToken {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long userId;

  private String tokenHash;

  private LocalDateTime expiresAt;

  private LocalDateTime revokedAt;

  private LocalDateTime createdAt;
}
