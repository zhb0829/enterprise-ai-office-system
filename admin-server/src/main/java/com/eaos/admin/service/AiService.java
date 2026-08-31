package com.eaos.admin.service;

public interface AiService {

  /** 调用 Python agent 服务健康检查，返回原始响应体 */
  String health();
}
