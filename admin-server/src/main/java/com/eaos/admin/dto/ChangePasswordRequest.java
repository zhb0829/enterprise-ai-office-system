package com.eaos.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/** 密码策略（Q17）：至少 10 位，且同时包含大小写字母与数字。 */
@Data
public class ChangePasswordRequest {

  @NotBlank(message = "原密码不能为空") private String oldPassword;

  @NotBlank(message = "新密码不能为空") @Pattern(
      regexp = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d).{10,}$",
      message = "密码至少 10 位，且需同时包含大写字母、小写字母和数字")
  private String newPassword;
}
