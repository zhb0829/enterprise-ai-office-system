package com.eaos.admin.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.eaos.admin.controller.AdminCreateUserRequest;
import com.eaos.admin.dto.ChangePasswordRequest;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

class PasswordPolicyValidationTest {

  private static Validator validator;

  @BeforeAll
  static void setUpValidator() {
    validator = Validation.buildDefaultValidatorFactory().getValidator();
  }

  @Test
  void acceptsSixCharacterPasswordWithRequiredCharacterClasses() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setOldPassword("OldPass123");
    request.setNewPassword("Aa1234");

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void acceptsDeveloperPassword() {
    AdminCreateUserRequest request = new AdminCreateUserRequest();
    request.setUsername("developer");
    request.setPassword("Bin123456");

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void rejectsPasswordShorterThanSixCharacters() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setOldPassword("OldPass123");
    request.setNewPassword("Aa123");

    assertThat(validator.validate(request)).isNotEmpty();
  }

  @Test
  void rejectsPasswordWithoutAllRequiredCharacterClasses() {
    AdminCreateUserRequest request = new AdminCreateUserRequest();
    request.setUsername("developer");
    request.setPassword("abcdef");

    assertThat(validator.validate(request)).isNotEmpty();
  }
}
