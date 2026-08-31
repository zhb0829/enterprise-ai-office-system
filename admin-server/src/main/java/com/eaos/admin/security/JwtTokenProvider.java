package com.eaos.admin.security;

import com.eaos.admin.config.SecretProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import javax.crypto.SecretKey;
import org.springframework.stereotype.Component;

@Component
public class JwtTokenProvider {

  private final SecretKey key;
  private final long expireMillis;

  public JwtTokenProvider(SecretProperties secretProperties) {
    // SecretProperties 启动时已 fail-fast 校验（空值/默认值拒绝启动）
    this.key =
        Keys.hmacShaKeyFor(secretProperties.getJwt().getSecret().getBytes(StandardCharsets.UTF_8));
    this.expireMillis = secretProperties.getJwt().getExpireMinutes() * 60 * 1000L;
  }

  public String generateToken(LoginUser user) {
    Date now = new Date();
    Date expiry = new Date(now.getTime() + expireMillis);
    return Jwts.builder()
        .subject(user.getUsername())
        .claim("userId", user.getId())
        .claim("nickname", user.getNickname())
        .claim("role", user.getRole())
        .claim("roles", List.of(user.getRole()))
        .claim("tenant_id", user.getTenantId())
        .issuedAt(now)
        .expiration(expiry)
        .signWith(key)
        .compact();
  }

  public Claims parseToken(String token) {
    return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
  }
}
