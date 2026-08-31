package com.eaos.admin.meeting.support;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

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

/** 会议资料磁盘存储：meeting-storage/{conferenceId}/。 */
@Service
public class MeetingStorageService {

    private final Path root;

    public MeetingStorageService(@Value("${eaos.meeting.storage-dir:meeting-storage}") String storageDir) {
        this.root = Path.of(storageDir).toAbsolutePath().normalize();
    }

    public StoredFile save(Long conferenceId, MultipartFile file) throws IOException {
        String original = file.getOriginalFilename() == null ? "unnamed" : file.getOriginalFilename();
        String name = original.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replace("..", "_");
        Path directory = root.resolve(String.valueOf(conferenceId)).normalize();
        if (!directory.startsWith(root)) {
            throw new IOException("非法存储路径");
        }
        Files.createDirectories(directory);
        Path target = directory.resolve(UUID.randomUUID() + "_" + name).normalize();
        if (!target.startsWith(directory)) {
            throw new IOException("非法文件名");
        }
        MessageDigest digest = sha256();
        try (InputStream in = new DigestInputStream(file.getInputStream(), digest);
             OutputStream out = Files.newOutputStream(target)) {
            in.transferTo(out);
        }
        return new StoredFile(target.toString(), HexFormat.of().formatHex(digest.digest()));
    }

    public String saveText(Long conferenceId, String filename, String content) throws IOException {
        Path directory = root.resolve(String.valueOf(conferenceId)).normalize();
        if (!directory.startsWith(root)) {
            throw new IOException("非法存储路径");
        }
        Files.createDirectories(directory);
        Path target = directory.resolve(UUID.randomUUID() + "_" + filename).normalize();
        if (!target.startsWith(directory)) {
            throw new IOException("非法文件名");
        }
        Files.writeString(target, content);
        return target.toString();
    }

    public void delete(String filePath) {
        if (filePath == null || filePath.isBlank()) {
            return;
        }
        try {
            Path target = Path.of(filePath).toAbsolutePath().normalize();
            if (target.startsWith(root)) {
                Files.deleteIfExists(target);
            }
        } catch (IOException ignored) {
            // 数据删除不应因本地文件已经不存在而失败。
        }
    }

    private MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("运行环境不支持 SHA-256", ex);
        }
    }

    public record StoredFile(String path, String sha256) {
    }
}
