package com.eaos.admin.security;

/** 统一密码策略：至少 6 位，且同时包含大小写字母与数字。 */
public final class PasswordPolicy {

  public static final String REGEX = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d).{6,}$";
  public static final String MESSAGE = "密码至少 6 位，且需同时包含大写字母、小写字母和数字";

  private PasswordPolicy() {}
}
