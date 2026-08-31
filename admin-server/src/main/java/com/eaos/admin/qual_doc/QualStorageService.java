package com.eaos.admin.qual_doc;

import com.eaos.admin.storage.FileStorage;
import java.io.IOException;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

/** 资质材料上传存储，落盘路径由统一 FileStorage 抽象管理。 */
@Service
public class QualStorageService {

  private final FileStorage fileStorage;

  public QualStorageService(FileStorage fileStorage) {
    this.fileStorage = fileStorage;
  }

  public String save(String folder, MultipartFile file) throws IOException {
    String original = file.getOriginalFilename() == null ? "upload" : file.getOriginalFilename();
    return fileStorage.store(folder, original, file.getInputStream()).path();
  }
}
