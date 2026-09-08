package com.eaos.admin.controller;

import com.eaos.admin.security.PasswordPolicy;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/** 管理端创建用户请求。密码策略：>=6 位 + 大小写 + 数字。 */
@Data
public class AdminCreateUserRequest {

  @NotBlank(message = "用户名不能为空") private String username;

  @NotBlank(message = "密码不能为空") @Pattern(
      regexp = PasswordPolicy.REGEX,
      message = PasswordPolicy.MESSAGE)
  private String password;

  private String nickname;

  private String role;
}
