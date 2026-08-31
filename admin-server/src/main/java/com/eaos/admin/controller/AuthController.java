package com.eaos.admin.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.dto.ChangePasswordRequest;
import com.eaos.admin.dto.LoginRequest;
import com.eaos.admin.dto.LoginResponse;
import com.eaos.admin.dto.RefreshTokenRequest;
import com.eaos.admin.entity.SysPasswordReset;
import com.eaos.admin.entity.SysUser;
import com.eaos.admin.mapper.SysPasswordResetMapper;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.security.JwtTokenProvider;
import com.eaos.admin.security.LoginUser;
import com.eaos.admin.security.RefreshTokenService;
import com.eaos.admin.security.SecurityUtils;
import jakarta.validation.Valid;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

  private final AuthenticationManager authenticationManager;
  private final JwtTokenProvider jwtTokenProvider;
  private final RefreshTokenService refreshTokenService;
  private final SysUserMapper sysUserMapper;
  private final SysPasswordResetMapper passwordResetMapper;
  private final PasswordEncoder passwordEncoder;

  @PostMapping("/login")
  public R<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
    Authentication authentication;
    try {
      authentication =
          authenticationManager.authenticate(
              new UsernamePasswordAuthenticationToken(
                  request.getUsername(), request.getPassword()));
    } catch (AuthenticationException ex) {
      return R.error(401, "用户名或密码错误");
    }
    LoginUser loginUser = (LoginUser) authentication.getPrincipal();
    SysUser user = sysUserMapper.selectById(loginUser.getId());
    boolean mustChangePassword = user != null && Boolean.TRUE.equals(user.getMustChangePassword());
    String accessToken = jwtTokenProvider.generateToken(loginUser);
    String refreshToken = refreshTokenService.issue(loginUser.getId());
    LoginResponse response =
        new LoginResponse(
            accessToken,
            refreshToken,
            loginUser.getId(),
            loginUser.getUsername(),
            loginUser.getNickname(),
            loginUser.getRole(),
            mustChangePassword);
    return R.ok(response);
  }

  @PostMapping("/refresh")
  public R<LoginResponse> refresh(@Valid @RequestBody RefreshTokenRequest request) {
    RefreshTokenService.Rotated rotated;
    try {
      rotated = refreshTokenService.rotate(request.getRefreshToken());
    } catch (IllegalArgumentException ex) {
      return R.error(401, "登录状态已失效，请重新登录");
    }
    SysUser user = sysUserMapper.selectById(rotated.userId());
    if (user == null || !Boolean.TRUE.equals(user.getEnabled())) {
      return R.error(401, "账号不可用");
    }
    LoginUser loginUser =
        new LoginUser(
            user.getId(),
            user.getUsername(),
            user.getPassword(),
            user.getNickname(),
            user.getRole(),
            user.getTenantId(),
            user.getEnabled());
    String accessToken = jwtTokenProvider.generateToken(loginUser);
    boolean mustChangePassword = Boolean.TRUE.equals(user.getMustChangePassword());
    LoginResponse response =
        new LoginResponse(
            accessToken,
            rotated.newToken(),
            user.getId(),
            user.getUsername(),
            user.getNickname(),
            user.getRole(),
            mustChangePassword);
    return R.ok(response);
  }

  @PostMapping("/logout")
  public R<Void> logout(@Valid @RequestBody RefreshTokenRequest request) {
    refreshTokenService.revoke(request.getRefreshToken());
    return R.ok();
  }

  /** 修改密码（含首登强制改密）：成功后吊销该用户全部刷新令牌。 */
  @PostMapping("/change-password")
  public R<Void> changePassword(@Valid @RequestBody ChangePasswordRequest request) {
    Long userId = SecurityUtils.currentUserId();
    if (userId == null) {
      return R.error(401, "未认证");
    }
    SysUser user = sysUserMapper.selectById(userId);
    if (user == null) {
      return R.error(401, "用户不存在");
    }
    if (!passwordEncoder.matches(request.getOldPassword(), user.getPassword())) {
      return R.error(400, "原密码不正确");
    }
    if (passwordEncoder.matches(request.getNewPassword(), user.getPassword())) {
      return R.error(400, "新密码不能与原密码相同");
    }
    user.setPassword(passwordEncoder.encode(request.getNewPassword()));
    user.setMustChangePassword(false);
    user.setUpdatedAt(LocalDateTime.now());
    sysUserMapper.updateById(user);
    SysPasswordReset reset = new SysPasswordReset();
    reset.setUserId(user.getId());
    reset.setResetAt(LocalDateTime.now());
    passwordResetMapper.insert(reset);
    refreshTokenService.revokeAll(user.getId());
    return R.ok();
  }
}
