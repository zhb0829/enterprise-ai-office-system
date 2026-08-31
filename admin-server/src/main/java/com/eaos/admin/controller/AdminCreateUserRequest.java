package com.eaos.admin.controller;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/** 管理端创建用户请求。密码策略：>=10 位 + 大小写 + 数字。 */
@Data
public class AdminCreateUserRequest {

  @NotBlank(message = "用户名不能为空") private String username;

  @NotBlank(message = "密码不能为空") @Pattern(
      regexp = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d).{10,}$",
      message = "密码至少 10 位，且需同时包含大写字母、小写字母和数字")
  private String password;

  private String nickname;

  private String role;
}
