package com.eaos.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class LoginResponse {

  private String token;
  private String refreshToken;
  private Long userId;
  private String username;
  private String nickname;
  private String role;
  private boolean mustChangePassword;
}
