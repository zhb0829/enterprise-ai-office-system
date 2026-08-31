package com.eaos.admin.common;

import java.io.Serializable;
import lombok.Getter;

@Getter
public class R<T> implements Serializable {

  private final int code;
  private final String message;
  private final T data;

  private R(int code, String message, T data) {
    this.code = code;
    this.message = message;
    this.data = data;
  }

  public static <T> R<T> ok() {
    return new R<>(0, "success", null);
  }

  public static <T> R<T> ok(T data) {
    return new R<>(0, "success", data);
  }

  public static <T> R<T> error(String message) {
    return new R<>(1, message, null);
  }

  public static <T> R<T> error(int code, String message) {
    return new R<>(code, message, null);
  }
}
