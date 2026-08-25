package com.eaos.admin.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.validation.BindException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(AuthenticationException.class)
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public R<Void> handleAuthentication(AuthenticationException e) {
        return R.error(401, "认证失败：" + e.getMessage());
    }

    @ExceptionHandler(AccessDeniedException.class)
    @ResponseStatus(HttpStatus.FORBIDDEN)
    public R<Void> handleAccessDenied(AccessDeniedException e) {
        return R.error(403, "无权限访问");
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public R<Void> handleValidation(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(f -> f.getField() + ": " + f.getDefaultMessage())
                .orElse("参数校验失败");
        return R.error(400, msg);
    }

    @ExceptionHandler(BindException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public R<Void> handleBind(BindException e) {
        return R.error(400, "参数绑定失败：" + e.getMessage());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public R<Void> handleIllegalArgument(IllegalArgumentException e) {
        return R.error(400, e.getMessage());
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public R<Void> handleDataIntegrityViolation(DataIntegrityViolationException e) {
        log.warn("数据约束冲突", e);
        if (e.getMessage() != null && e.getMessage().contains("source_config_url_key")) {
            return R.error(409, "该采集来源 URL 已存在，请直接使用或修改现有来源");
        }
        return R.error(409, "数据已存在或不符合数据约束");
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public R<Void> handleException(Exception e) {
        log.error("系统异常", e);
        return R.error(500, "系统异常：" + e.getMessage());
    }
}
