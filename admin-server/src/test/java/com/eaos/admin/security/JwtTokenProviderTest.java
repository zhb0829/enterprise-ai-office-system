package com.eaos.admin.security;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.eaos.admin.config.SecretProperties;
import io.jsonwebtoken.Claims;
import java.util.List;
import org.junit.jupiter.api.Test;

class JwtTokenProviderTest {

  private JwtTokenProvider newProvider() {
    SecretProperties properties = new SecretProperties();
    properties.getJwt().setSecret("unit-test-jwt-secret-0123456789abcdef0123456789abcdef");
    properties.getJwt().setExpireMinutes(120);
    return new JwtTokenProvider(properties);
  }

  private LoginUser sampleUser() {
    return new LoginUser(7L, "tester", "pwd", "测试用户", "USER", 3L, true);
  }

  @Test
  void tokenCarriesTenantRolesAndUserClaims() {
    Claims claims = newProvider().parseToken(newProvider().generateToken(sampleUser()));
    assertEquals("tester", claims.getSubject());
    assertEquals(7, claims.get("userId", Integer.class));
    assertEquals("USER", claims.get("role", String.class));
    assertEquals(List.of("USER"), claims.get("roles", List.class));
    assertEquals(3, claims.get("tenant_id", Integer.class));
  }

  @Test
  void expiredTokenIsRejected() {
    SecretProperties properties = new SecretProperties();
    properties.getJwt().setSecret("unit-test-jwt-secret-0123456789abcdef0123456789abcdef");
    properties.getJwt().setExpireMinutes(0);
    JwtTokenProvider provider = new JwtTokenProvider(properties);
    String token = provider.generateToken(sampleUser());
    assertThrows(Exception.class, () -> provider.parseToken(token));
  }

  @Test
  void tamperedSignatureIsRejected() {
    JwtTokenProvider provider = newProvider();
    String token = provider.generateToken(sampleUser());
    String tampered = token.substring(0, token.length() - 2) + "xx";
    assertThrows(Exception.class, () -> provider.parseToken(tampered));
  }
}
