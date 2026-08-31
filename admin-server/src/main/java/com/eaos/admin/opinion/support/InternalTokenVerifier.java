package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.config.OpinionServiceProperties;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** 校验内部服务令牌（Python Worker → Java 基于 X-Internal-Token），常量时间比较。 */
@Component
@RequiredArgsConstructor
public class InternalTokenVerifier {

  public static final String HEADER = "X-Internal-Token";

  private final OpinionServiceProperties properties;

  public boolean verify(HttpServletRequest request) {
    return constantTimeEquals(properties.getInternalToken(), request.getHeader(HEADER));
  }

  static boolean constantTimeEquals(String expected, String provided) {
    byte[] a = (expected == null ? "" : expected).getBytes(StandardCharsets.UTF_8);
    byte[] b = (provided == null ? "" : provided).getBytes(StandardCharsets.UTF_8);
    return MessageDigest.isEqual(a, b);
  }
}
