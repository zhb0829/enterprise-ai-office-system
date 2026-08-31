package com.eaos.admin.meeting.support;

import com.eaos.admin.security.LoginUser;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/** 当前登录用户（dev 关闭 security 时安全返回 null）。 */
public final class CurrentUser {

  private CurrentUser() {}

  public static LoginUser current() {
    Authentication auth = SecurityContextHolder.getContext().getAuthentication();
    if (auth != null && auth.getPrincipal() instanceof LoginUser loginUser) {
      return loginUser;
    }
    return null;
  }

  public static Long id() {
    LoginUser user = current();
    return user == null ? null : user.getId();
  }

  public static String username() {
    LoginUser user = current();
    return user == null ? "" : user.getUsername();
  }

  public static boolean isAdmin() {
    LoginUser user = current();
    return user != null && "ADMIN".equalsIgnoreCase(user.getRole());
  }
}
