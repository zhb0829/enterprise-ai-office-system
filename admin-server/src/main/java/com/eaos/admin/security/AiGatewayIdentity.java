package com.eaos.admin.security;

import com.eaos.admin.common.TraceIdFilter;
import com.eaos.admin.config.AiServiceProperties;
import java.net.HttpURLConnection;
import java.util.Locale;
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
    // G7 三角色租户治理：角色是职责口径，权限是判定口径，两者一起下发。
    // Python 侧只做收缩（有效权限 = 角色基线 ∩ 本字符串），不一致时以 Python 侧角色基线为准，
    // 即失败方向是收紧而不是提权。
    String role = tenantRoleOf(user.getRole());
    connection.setRequestProperty("X-User-Role", role);
    connection.setRequestProperty("X-User-Permissions", tenantPermissionsOf(role));
  }

  /** 账号角色 → 租户治理角色：ADMIN 管租户，TENANT_ADMIN 管知识库，其余只提问。 */
  private static String tenantRoleOf(String accountRole) {
    String value = accountRole == null ? "" : accountRole.trim().toUpperCase(Locale.ROOT);
    return switch (value) {
      case "ADMIN" -> "platform_admin";
      case "TENANT_ADMIN" -> "tenant_admin";
      default -> "member";
    };
  }

  /** 角色权限口径，必须与 Python 侧 app/agent/access.py 的角色基线一致。 */
  private static String tenantPermissionsOf(String role) {
    String member = "policy:read,materials:read,meeting:read,memory:read,memory:write";
    if ("member".equals(role)) {
      return member;
    }
    String tenantAdmin =
        member
            + ",knowledge:read,knowledge:write,knowledge:publish,materials:write,draft:write,"
            + "draft:review,draft:verify,templates:write,opinion:read,agent:audit,"
            + "memory:department:write,memory:tenant:write";
    if ("tenant_admin".equals(role)) {
      return tenantAdmin;
    }
    return tenantAdmin + ",agent:admin";
  }
}
