package com.eaos.admin.controller;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.eaos.admin.mapper.SysRoleMapper;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.mapper.SysUserRoleMapper;
import com.eaos.admin.security.LoginUser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AdminUserControllerTest {

  @Mock private SysUserMapper sysUserMapper;
  @Mock private SysRoleMapper sysRoleMapper;
  @Mock private SysUserRoleMapper sysUserRoleMapper;
  @Mock private PasswordEncoder passwordEncoder;

  @InjectMocks private AdminUserController controller;

  @AfterEach
  void clearContext() {
    SecurityContextHolder.clearContext();
  }

  @Test
  void deleteRejectsNonAdminWithoutDeletingUser() {
    setCurrentUser(2L, "USER");

    assertThrows(IllegalArgumentException.class, () -> controller.delete(1L));

    verifyNoInteractions(sysUserMapper, sysUserRoleMapper);
  }

  @Test
  void deleteAllowsAdmin() {
    setCurrentUser(2L, "ADMIN");

    controller.delete(1L);

    verify(sysUserMapper).deleteById(1L);
    verify(sysUserRoleMapper).delete(any());
  }

  private void setCurrentUser(Long id, String role) {
    LoginUser user = new LoginUser(id, "user", "secret", "用户", role, true);
    UsernamePasswordAuthenticationToken authentication =
        new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities());
    SecurityContextHolder.getContext().setAuthentication(authentication);
  }
}
