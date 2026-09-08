package com.eaos.admin.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.eaos.admin.entity.SysRole;
import com.eaos.admin.entity.SysTenant;
import com.eaos.admin.entity.SysUser;
import com.eaos.admin.entity.SysUserRole;
import com.eaos.admin.mapper.SysRoleMapper;
import com.eaos.admin.mapper.SysTenantMapper;
import com.eaos.admin.mapper.SysUserMapper;
import com.eaos.admin.mapper.SysUserRoleMapper;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** 首启播种（Q17）：随机 16 位管理员密码打印控制台 + 强制首登改密； 播种默认租户 demo-enterprise 与内置角色。 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DataInitializer implements ApplicationRunner {

  private static final String DEFAULT_TENANT_CODE = "demo-enterprise";
  private static final SecureRandom RANDOM = new SecureRandom();
  private static final String LOWER = "abcdefghijkmnpqrstuvwxyz";
  private static final String UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  private static final String DIGITS = "23456789";
  private static final String ALL = LOWER + UPPER + DIGITS;

  private final SysUserMapper sysUserMapper;
  private final SysTenantMapper sysTenantMapper;
  private final SysRoleMapper sysRoleMapper;
  private final SysUserRoleMapper sysUserRoleMapper;
  private final PasswordEncoder passwordEncoder;

  @Override
  @Transactional
  public void run(ApplicationArguments args) {
    Long tenantId = seedTenant();
    Long adminRoleId = seedRole("ADMIN", "系统管理员");
    seedRole("USER", "普通用户");

    Long count =
        sysUserMapper.selectCount(
            new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, "admin"));
    if (count == null || count == 0L) {
      String password = generatePassword(16);
      SysUser admin = new SysUser();
      admin.setUsername("admin");
      admin.setPassword(passwordEncoder.encode(password));
      admin.setNickname("系统管理员");
      admin.setRole("ADMIN");
      admin.setEnabled(true);
      admin.setTenantId(tenantId);
      admin.setMustChangePassword(true);
      admin.setCreatedAt(LocalDateTime.now());
      admin.setUpdatedAt(LocalDateTime.now());
      sysUserMapper.insert(admin);

      SysUserRole binding = new SysUserRole();
      binding.setUserId(admin.getId());
      binding.setRoleId(adminRoleId);
      sysUserRoleMapper.insert(binding);

      log.warn("==============================================================");
      log.warn("  首次启动已创建管理员账号 admin，初始密码：{}", password);
      log.warn("  请立即使用该密码登录，系统已标记首登强制修改密码！");
      log.warn("==============================================================");
    } else {
      SysUser admin =
          sysUserMapper.selectOne(
              new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, "admin"));
      if (admin != null
          && Boolean.TRUE.equals(passwordEncoder.matches("admin123", admin.getPassword()))) {
        admin.setMustChangePassword(true);
        admin.setUpdatedAt(LocalDateTime.now());
        sysUserMapper.updateById(admin);
        log.warn("检测到历史默认密码 admin123，已标记 admin 首登强制修改密码");
      }
    }
  }

  private Long seedTenant() {
    SysTenant tenant =
        sysTenantMapper.selectOne(
            new LambdaQueryWrapper<SysTenant>().eq(SysTenant::getCode, DEFAULT_TENANT_CODE));
    if (tenant != null) {
      return tenant.getId();
    }
    tenant = new SysTenant();
    tenant.setCode(DEFAULT_TENANT_CODE);
    tenant.setName("演示企业");
    sysTenantMapper.insert(tenant);
    return tenant.getId();
  }

  private Long seedRole(String code, String name) {
    SysRole role =
        sysRoleMapper.selectOne(new LambdaQueryWrapper<SysRole>().eq(SysRole::getCode, code));
    if (role != null) {
      return role.getId();
    }
    role = new SysRole();
    role.setCode(code);
    role.setName(name);
    sysRoleMapper.insert(role);
    return role.getId();
  }

  /** 生成满足密码策略（大小写 + 数字，>=6 位）的随机密码。 */
  private String generatePassword(int length) {
    StringBuilder sb = new StringBuilder(length);
    sb.append(LOWER.charAt(RANDOM.nextInt(LOWER.length())));
    sb.append(UPPER.charAt(RANDOM.nextInt(UPPER.length())));
    sb.append(DIGITS.charAt(RANDOM.nextInt(DIGITS.length())));
    for (int i = sb.length(); i < length; i++) {
      sb.append(ALL.charAt(RANDOM.nextInt(ALL.length())));
    }
    // Fisher-Yates 洗牌，避免固定位置的字符类别
    for (int i = length - 1; i > 0; i--) {
      int j = RANDOM.nextInt(i + 1);
      char tmp = sb.charAt(i);
      sb.setCharAt(i, sb.charAt(j));
      sb.setCharAt(j, tmp);
    }
    return sb.toString();
  }
}
