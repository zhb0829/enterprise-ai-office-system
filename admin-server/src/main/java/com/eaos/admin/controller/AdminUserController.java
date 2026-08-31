package com.eaos.admin.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.common.R;
import com.eaos.admin.dto.ChangePasswordRequest;
import com.eaos.admin.entity.SysRole;
import com.eaos.admin.entity.SysUser;
import com.eaos.admin.mapper.SysRoleMapper;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.mapper.SysUserRoleMapper;
import com.eaos.admin.security.SecurityUtils;
import jakarta.validation.Valid;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 用户管理（管理端，仅管理员）：CRUD、启用/禁用、重置密码。 */
@RestController
@RequestMapping("/api/admin/users")
@RequiredArgsConstructor
public class AdminUserController {

  private final SysUserMapper sysUserMapper;
  private final SysRoleMapper sysRoleMapper;
  private final SysUserRoleMapper sysUserRoleMapper;
  private final PasswordEncoder passwordEncoder;

  @GetMapping
  public R<Map<String, Object>> page(
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int pageSize,
      @RequestParam(required = false) String keyword) {
    requireAdmin();
    LambdaQueryWrapper<SysUser> wrapper = Wrappers.lambdaQuery(SysUser.class);
    if (keyword != null && !keyword.isBlank()) {
      wrapper.and(
          w ->
              w.like(SysUser::getUsername, keyword.trim())
                  .or()
                  .like(SysUser::getNickname, keyword.trim()));
    }
    long total = sysUserMapper.selectCount(wrapper);
    pageSize = Math.min(100, Math.max(1, pageSize));
    wrapper
        .orderByAsc(SysUser::getId)
        .last("LIMIT " + pageSize + " OFFSET " + ((Math.max(1, page) - 1) * pageSize));
    List<SysUser> users = sysUserMapper.selectList(wrapper);
    users.forEach(user -> user.setPassword(null));
    return R.ok(Map.of("items", users, "total", total, "page", page, "pageSize", pageSize));
  }

  @PostMapping
  @Transactional
  public R<SysUser> create(@RequestBody @Valid AdminCreateUserRequest request) {
    requireAdmin();
    Long exists =
        sysUserMapper.selectCount(
            Wrappers.lambdaQuery(SysUser.class).eq(SysUser::getUsername, request.getUsername()));
    if (exists != null && exists > 0) {
      throw new IllegalArgumentException("用户名已存在");
    }
    SysUser user = new SysUser();
    user.setUsername(request.getUsername());
    user.setPassword(passwordEncoder.encode(request.getPassword()));
    user.setNickname(request.getNickname() == null ? request.getUsername() : request.getNickname());
    user.setRole(request.getRole() == null ? "USER" : request.getRole());
    user.setEnabled(true);
    user.setCreatedAt(LocalDateTime.now());
    user.setUpdatedAt(LocalDateTime.now());
    sysUserMapper.insert(user);
    user.setPassword(null);
    return R.ok(user);
  }

  @GetMapping("/roles")
  public R<List<SysRole>> roles() {
    requireAdmin();
    return R.ok(sysRoleMapper.selectList(Wrappers.emptyWrapper()));
  }

  @PutMapping("/{id}")
  @Transactional
  public R<Void> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
    requireAdmin();
    SysUser user = sysUserMapper.selectById(id);
    if (user == null) {
      throw new IllegalArgumentException("用户不存在");
    }
    if (body.containsKey("nickname") && body.get("nickname") != null) {
      user.setNickname(String.valueOf(body.get("nickname")));
    }
    if (body.containsKey("role") && body.get("role") != null) {
      user.setRole(String.valueOf(body.get("role")));
    }
    if (body.containsKey("enabled") && body.get("enabled") != null) {
      user.setEnabled(Boolean.parseBoolean(String.valueOf(body.get("enabled"))));
    }
    user.setUpdatedAt(LocalDateTime.now());
    sysUserMapper.updateById(user);
    return R.ok();
  }

  @DeleteMapping("/{id}")
  @Transactional
  public R<Void> delete(@PathVariable Long id) {
    Long operatorId = SecurityUtils.currentUserId();
    if (operatorId != null && operatorId.equals(id)) {
      throw new IllegalArgumentException("不能删除当前登录账号");
    }
    sysUserMapper.deleteById(id);
    sysUserRoleMapper.delete(
        Wrappers.lambdaQuery(com.eaos.admin.entity.SysUserRole.class)
            .eq(com.eaos.admin.entity.SysUserRole::getUserId, id));
    return R.ok();
  }

  /** 重置密码：满足密码策略，重置后强制首登改密。 */
  @PostMapping("/{id}/reset-password")
  @Transactional
  public R<Void> resetPassword(
      @PathVariable Long id, @RequestBody @Valid ChangePasswordRequest request) {
    requireAdmin();
    SysUser user = sysUserMapper.selectById(id);
    if (user == null) {
      throw new IllegalArgumentException("用户不存在");
    }
    user.setPassword(passwordEncoder.encode(request.getNewPassword()));
    user.setMustChangePassword(true);
    user.setUpdatedAt(LocalDateTime.now());
    sysUserMapper.updateById(user);
    return R.ok();
  }

  private void requireAdmin() {
    if (!SecurityUtils.isAdmin()) {
      throw new IllegalArgumentException("仅系统管理员可管理用户");
    }
  }
}
