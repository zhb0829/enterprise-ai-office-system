package com.eaos.admin.security;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/** 全局统一的当前登录用户读取入口。 */
public final class SecurityUtils {

  private SecurityUtils() {}

  public static LoginUser current() {
    Authentication auth = SecurityContextHolder.getContext().getAuthentication();
    if (auth != null && auth.getPrincipal() instanceof LoginUser loginUser) {
      return loginUser;
    }
    return null;
  }

  public static Long currentUserId() {
    LoginUser user = current();
    return user == null ? null : user.getId();
  }

  public static boolean isAdmin() {
    LoginUser user = current();
    return user != null && "ADMIN".equalsIgnoreCase(user.getRole());
  }
}
