package com.eaos.admin.storage;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.UUID;
import org.springframework.stereotype.Component;

/** 本地磁盘实现：{eaos.storage.root}/{folder}/{uuid}_{filename}。 */
@Component
public class LocalStorage implements FileStorage {

  private final Path root;

  public LocalStorage(StorageProperties properties) {
    this.root = Path.of(properties.getRoot()).toAbsolutePath().normalize();
  }

  @Override
  public StoredFile store(String folder, String originalFilename, InputStream in)
      throws IOException {
    Path directory = requireSafeDirectory(folder);
    String name = sanitize(originalFilename);
    Path target = directory.resolve(UUID.randomUUID() + "_" + name).normalize();
    if (!target.startsWith(directory)) {
      throw new IOException("非法文件名");
    }
    MessageDigest digest = sha256();
    try (InputStream source = new DigestInputStream(in, digest);
        OutputStream out = Files.newOutputStream(target)) {
      source.transferTo(out);
    }
    return new StoredFile(target.toString(), HexFormat.of().formatHex(digest.digest()));
  }

  @Override
  public String storeText(String folder, String filename, String content) throws IOException {
    Path directory = requireSafeDirectory(folder);
    String name = sanitize(filename);
    Path target = directory.resolve(UUID.randomUUID() + "_" + name).normalize();
    if (!target.startsWith(directory)) {
      throw new IOException("非法文件名");
    }
    Files.writeString(target, content);
    return target.toString();
  }

  @Override
  public void delete(String storedPath) {
    if (storedPath == null || storedPath.isBlank()) {
      return;
    }
    try {
      Path target = Path.of(storedPath).toAbsolutePath().normalize();
      if (target.startsWith(root)) {
        Files.deleteIfExists(target);
      }
    } catch (IOException ignored) {
      // 数据删除不应因本地文件已经不存在而失败。
    }
  }

  private Path requireSafeDirectory(String folder) throws IOException {
    if (folder == null || folder.isBlank()) {
      throw new IOException("存储目录不能为空");
    }
    Path directory = root.resolve(folder).normalize();
    if (!directory.startsWith(root)) {
      throw new IOException("非法存储路径");
    }
    Files.createDirectories(directory);
    return directory;
  }

  private String sanitize(String original) {
    String name = original == null || original.isBlank() ? "unnamed" : original;
    return name.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replace("..", "_");
  }

  private MessageDigest sha256() {
    try {
      return MessageDigest.getInstance("SHA-256");
    } catch (NoSuchAlgorithmException ex) {
      throw new IllegalStateException("运行环境不支持 SHA-256", ex);
    }
  }
}
