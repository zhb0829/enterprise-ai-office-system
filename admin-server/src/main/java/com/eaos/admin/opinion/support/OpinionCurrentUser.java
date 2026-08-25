package com.eaos.admin.opinion.support;

import com.eaos.admin.security.LoginUser;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/** A helper for reading the authenticated principal. In dev mode (security disabled)
 * the context may be empty, so a null-safe accessor is provided. */
public final class OpinionCurrentUser {

    private OpinionCurrentUser() {
    }

    public static Long id() {
        LoginUser user = current();
        return user == null ? null : user.getId();
    }

    public static String username() {
        LoginUser user = current();
        return user == null ? "" : user.getUsername();
    }

    public static String role() {
        LoginUser user = current();
        return user == null ? "" : user.getRole();
    }

    public static boolean isAdmin() {
        return "ADMIN".equalsIgnoreCase(role());
    }

    public static boolean isAuthenticated() {
        return current() != null;
    }

    public static LoginUser current() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof LoginUser loginUser) {
            return loginUser;
        }
        return null;
    }
}
