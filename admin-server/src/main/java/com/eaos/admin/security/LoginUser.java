package com.eaos.admin.security;

import java.util.Collection;
import java.util.List;
import lombok.Getter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;

@Getter
public class LoginUser implements UserDetails {

  private final Long id;
  private final String username;
  private final String password;
  private final String nickname;
  private final String role;
  private final Long tenantId;
  private final boolean enabled;

  public LoginUser(
      Long id, String username, String password, String nickname, String role, boolean enabled) {
    this(id, username, password, nickname, role, null, enabled);
  }

  public LoginUser(
      Long id,
      String username,
      String password,
      String nickname,
      String role,
      Long tenantId,
      boolean enabled) {
    this.id = id;
    this.username = username;
    this.password = password;
    this.nickname = nickname;
    this.role = role;
    this.tenantId = tenantId;
    this.enabled = enabled;
  }

  @Override
  public Collection<? extends GrantedAuthority> getAuthorities() {
    return List.of(new SimpleGrantedAuthority("ROLE_" + role));
  }

  @Override
  public boolean isAccountNonExpired() {
    return true;
  }

  @Override
  public boolean isAccountNonLocked() {
    return true;
  }

  @Override
  public boolean isCredentialsNonExpired() {
    return true;
  }

  @Override
  public boolean isEnabled() {
    return enabled;
  }
}
