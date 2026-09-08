package com.eaos.admin.storage;

import java.io.IOException;
import java.io.InputStream;

/** 统一文件存储抽象。默认 {@link LocalStorage} 落本地磁盘（单机 volume）， 多实例部署时替换为对象存储实现（如 S3/MinIO），业务代码无感知。 */
public interface FileStorage {

  /** 保存二进制文件，返回落盘路径与 SHA-256 摘要。 */
  StoredFile store(String folder, String originalFilename, InputStream in) throws IOException;

  /** 保存文本文件，返回落盘路径。 */
  String storeText(String folder, String filename, String content) throws IOException;

  /** 删除已存储文件；路径不属于本存储根目录时静默忽略。 */
  void delete(String storedPath);

  record StoredFile(String path, String sha256) {}
}
