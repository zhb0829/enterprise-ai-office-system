package com.eaos.admin.meeting.support;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** 校验内部服务令牌（Python → Java 基于 X-Internal-Token），常量时间比较。 */
@Component
public class MeetingInternalTokenVerifier {

    public static final String HEADER = "X-Internal-Token";

    private final String token;

    public MeetingInternalTokenVerifier(
            @Value("${eaos.meeting.internal-token:eaos-meeting-internal-dev-token}") String token) {
        this.token = token;
    }

    public boolean verify(HttpServletRequest request) {
        return constantTimeEquals(token, request.getHeader(HEADER));
    }

    static boolean constantTimeEquals(String expected, String provided) {
        byte[] a = (expected == null ? "" : expected).getBytes(StandardCharsets.UTF_8);
        byte[] b = (provided == null ? "" : provided).getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }
}
