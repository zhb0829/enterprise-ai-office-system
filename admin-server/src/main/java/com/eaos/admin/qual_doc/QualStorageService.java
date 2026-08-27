package com.eaos.admin.qual_doc;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.UUID;

@Service
public class QualStorageService {

    private final Path root;

    public QualStorageService(@Value("${eaos.qual.storage-dir:qual-storage}") String storageDir) {
        this.root = Path.of(storageDir).toAbsolutePath().normalize();
    }

    public String save(String folder, MultipartFile file) throws IOException {
        String original = file.getOriginalFilename() == null ? "upload" : file.getOriginalFilename();
        String name = original.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replace("..", "_");
        Path directory = root.resolve(folder).normalize();
        if (!directory.startsWith(root)) {
            throw new IOException("非法存储路径");
        }
        Files.createDirectories(directory);
        Path target = directory.resolve(UUID.randomUUID() + "_" + name).normalize();
        if (!target.startsWith(directory)) {
            throw new IOException("非法文件名");
        }
        Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
        return target.toString();
    }
}
