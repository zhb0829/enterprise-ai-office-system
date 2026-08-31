package com.eaos.admin.security;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.eaos.admin.entity.SysRefreshToken;
import com.eaos.admin.mapper.SysRefreshTokenMapper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class RefreshTokenServiceTest {

  @Mock private SysRefreshTokenMapper refreshTokenMapper;

  @InjectMocks private RefreshTokenService service;

  @BeforeEach
  void setUp() {
    ReflectionTestUtils.setField(service, "refreshExpireDays", 7L);
  }

  private String hashOf(String raw) {
    try {
      MessageDigest digest = MessageDigest.getInstance("SHA-256");
      return HexFormat.of().formatHex(digest.digest(raw.getBytes(StandardCharsets.UTF_8)));
    } catch (Exception ex) {
      throw new IllegalStateException(ex);
    }
  }

  @Test
  void issueStoresHashOnlyAndReturnsRawToken() {
    when(refreshTokenMapper.insert(any(SysRefreshToken.class)))
        .thenAnswer(
            invocation -> {
              SysRefreshToken entity = invocation.getArgument(0);
              entity.setId(1L);
              return 1;
            });

    String raw = service.issue(5L);

    ArgumentCaptor<SysRefreshToken> captor = ArgumentCaptor.forClass(SysRefreshToken.class);
    verify(refreshTokenMapper).insert(captor.capture());
    assertEquals(64, captor.getValue().getTokenHash().length());
    assertNotEquals(raw, captor.getValue().getTokenHash());
    assertNotNull(captor.getValue().getExpiresAt());
  }

  @Test
  void rotateRevokesOldAndIssuesNew() {
    String raw = service.issue(5L);
    SysRefreshToken stored = new SysRefreshToken();
    stored.setId(1L);
    stored.setUserId(5L);
    stored.setTokenHash(hashOf(raw));
    stored.setExpiresAt(LocalDateTime.now().plusDays(7));
    when(refreshTokenMapper.selectOne(any())).thenReturn(stored);

    RefreshTokenService.Rotated rotated = service.rotate(raw);

    assertNotNull(stored.getRevokedAt());
    assertEquals(5L, rotated.userId());
    assertNotEquals(raw, rotated.newToken());
  }

  @Test
  void rotateRejectsRevokedOrExpiredToken() {
    String raw = service.issue(5L);
    SysRefreshToken revoked = new SysRefreshToken();
    revoked.setUserId(5L);
    revoked.setTokenHash(hashOf(raw));
    revoked.setExpiresAt(LocalDateTime.now().plusDays(7));
    revoked.setRevokedAt(LocalDateTime.now().minusMinutes(1));
    when(refreshTokenMapper.selectOne(any())).thenReturn(revoked);
    assertThrows(IllegalArgumentException.class, () -> service.rotate(raw));

    SysRefreshToken expired = new SysRefreshToken();
    expired.setUserId(6L);
    expired.setTokenHash(hashOf("another-token"));
    expired.setExpiresAt(LocalDateTime.now().minusDays(1));
    when(refreshTokenMapper.selectOne(any())).thenReturn(expired);
    assertThrows(IllegalArgumentException.class, () -> service.rotate("another-token"));
  }

  @Test
  void revokeAllOnlyTouchesUserTokens() {
    service.revokeAll(7L);

    verify(refreshTokenMapper, times(1)).update(any(), any());
  }
}
