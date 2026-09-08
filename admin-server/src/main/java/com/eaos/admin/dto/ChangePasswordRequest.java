package com.eaos.admin.dto;

import com.eaos.admin.security.PasswordPolicy;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/** 密码策略：至少 6 位，且同时包含大小写字母与数字。 */
@Data
public class ChangePasswordRequest {

  @NotBlank(message = "原密码不能为空") private String oldPassword;

  @NotBlank(message = "新密码不能为空") @Pattern(
      regexp = PasswordPolicy.REGEX,
      message = PasswordPolicy.MESSAGE)
  private String newPassword;
}
