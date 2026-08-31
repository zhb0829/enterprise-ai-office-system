package com.eaos.admin.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.eaos.admin.entity.SysRefreshToken;
import com.eaos.admin.mapper.SysRefreshTokenMapper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 刷新令牌签发/轮换/吊销：数据库只存 SHA-256 哈希，明文仅在签发时返回一次。 */
@Service
@RequiredArgsConstructor
public class RefreshTokenService {

  private static final SecureRandom RANDOM = new SecureRandom();

  private final SysRefreshTokenMapper refreshTokenMapper;

  @Value("${eaos.jwt.refresh-expire-days:7}")
  private long refreshExpireDays;

  @Transactional
  public String issue(Long userId) {
    String raw = newToken();
    SysRefreshToken entity = new SysRefreshToken();
    entity.setUserId(userId);
    entity.setTokenHash(hash(raw));
    entity.setExpiresAt(LocalDateTime.now().plusDays(refreshExpireDays));
    refreshTokenMapper.insert(entity);
    return raw;
  }

  /** 校验并轮换：旧令牌吊销，签发新令牌。返回 {userId, newToken}。 */
  @Transactional
  public Rotated rotate(String rawToken) {
    if (rawToken == null || rawToken.isBlank()) {
      throw new IllegalArgumentException("refresh token 不能为空");
    }
    SysRefreshToken stored =
        refreshTokenMapper.selectOne(
            new LambdaQueryWrapper<SysRefreshToken>()
                .eq(SysRefreshToken::getTokenHash, hash(rawToken)));
    if (stored == null
        || stored.getRevokedAt() != null
        || stored.getExpiresAt().isBefore(LocalDateTime.now())) {
      throw new IllegalArgumentException("refresh token 无效或已过期");
    }
    stored.setRevokedAt(LocalDateTime.now());
    refreshTokenMapper.updateById(stored);
    String raw = newToken();
    SysRefreshToken replacement = new SysRefreshToken();
    replacement.setUserId(stored.getUserId());
    replacement.setTokenHash(hash(raw));
    replacement.setExpiresAt(LocalDateTime.now().plusDays(refreshExpireDays));
    refreshTokenMapper.insert(replacement);
    return new Rotated(stored.getUserId(), raw);
  }

  @Transactional
  public void revoke(String rawToken) {
    if (rawToken == null || rawToken.isBlank()) {
      return;
    }
    SysRefreshToken stored =
        refreshTokenMapper.selectOne(
            new LambdaQueryWrapper<SysRefreshToken>()
                .eq(SysRefreshToken::getTokenHash, hash(rawToken)));
    if (stored != null && stored.getRevokedAt() == null) {
      stored.setRevokedAt(LocalDateTime.now());
      refreshTokenMapper.updateById(stored);
    }
  }

  /** 吊销某用户全部刷新令牌（改密后强制全端下线）。 */
  @Transactional
  public void revokeAll(Long userId) {
    SysRefreshToken probe = new SysRefreshToken();
    probe.setRevokedAt(LocalDateTime.now());
    refreshTokenMapper.update(
        probe,
        new LambdaQueryWrapper<SysRefreshToken>()
            .eq(SysRefreshToken::getUserId, userId)
            .isNull(SysRefreshToken::getRevokedAt));
  }

  private String newToken() {
    byte[] bytes = new byte[32];
    RANDOM.nextBytes(bytes);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
  }

  private String hash(String raw) {
    try {
      MessageDigest digest = MessageDigest.getInstance("SHA-256");
      return HexFormat.of().formatHex(digest.digest(raw.getBytes(StandardCharsets.UTF_8)));
    } catch (NoSuchAlgorithmException ex) {
      throw new IllegalStateException("运行环境不支持 SHA-256", ex);
    }
  }

  public record Rotated(Long userId, String newToken) {}
}
