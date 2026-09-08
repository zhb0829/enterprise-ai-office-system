package com.eaos.admin.storage;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "eaos.storage")
public class StorageProperties {

  /** 文件存储根目录，容器内挂载统一 volume。 */
  private String root = "storage";
}
