package com.eaos.admin.meeting.support;

import com.eaos.admin.storage.FileStorage;
import java.io.IOException;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

/** 会议资料磁盘存储：{eaos.storage.root}/{conferenceId}/。 */
@Service
public class MeetingStorageService {

  private final FileStorage fileStorage;

  public MeetingStorageService(FileStorage fileStorage) {
    this.fileStorage = fileStorage;
  }

  public FileStorage.StoredFile save(Long conferenceId, MultipartFile file) throws IOException {
    String original = file.getOriginalFilename() == null ? "unnamed" : file.getOriginalFilename();
    return fileStorage.store(String.valueOf(conferenceId), original, file.getInputStream());
  }

  public String saveText(Long conferenceId, String filename, String content) throws IOException {
    return fileStorage.storeText(String.valueOf(conferenceId), filename, content);
  }

  public void delete(String filePath) {
    fileStorage.delete(filePath);
  }
}
