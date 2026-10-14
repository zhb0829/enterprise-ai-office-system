package com.eaos.admin.security;

import com.eaos.admin.common.TraceIdFilter;
import com.eaos.admin.config.AiServiceProperties;
import java.net.HttpURLConnection;
import org.slf4j.MDC;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/** Identity is derived exclusively from the authenticated gateway context. */
public final class AiGatewayIdentity {
  private AiGatewayIdentity() {}

  public static void apply(HttpURLConnection connection, AiServiceProperties properties) {
    connection.setRequestProperty("X-Internal-Token", properties.getInternalToken());
    String trace = MDC.get("traceId");
    if (trace != null) connection.setRequestProperty(TraceIdFilter.HEADER, trace);
    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    if (authentication == null || !authentication.isAuthenticated()
        || !(authentication.getPrincipal() instanceof LoginUser user)) return;
    connection.setRequestProperty("X-User-Id", String.valueOf(user.getId()));
    // The existing account model is single-tenant; client organization headers are never trusted.
    connection.setRequestProperty("X-Tenant-Id", "default");
    connection.setRequestProperty("X-Department-Id", "");
    connection.setRequestProperty("X-Data-Clearance", "internal");
    connection.setRequestProperty("X-Public-Only", "false");
    String permissions = "policy:read,materials:read,materials:write,draft:write,draft:verify,"
        + "meeting:read,memory:read,memory:write,knowledge:read,opinion:read";
    if ("ADMIN".equals(user.getRole())) {
      permissions += ",templates:write,draft:review,agent:audit,agent:admin,knowledge:write,"
          + "knowledge:publish,memory:department:write,memory:tenant:write";
    }
    connection.setRequestProperty("X-User-Permissions", permissions);
  }
}
