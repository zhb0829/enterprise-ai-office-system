package com.eaos.admin.storage;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class LocalStorageTest {

  @TempDir Path tempDir;

  private LocalStorage newStorage() {
    StorageProperties properties = new StorageProperties();
    properties.setRoot(tempDir.toString());
    return new LocalStorage(properties);
  }

  @Test
  void storeWritesFileUnderRootAndReturnsSha256() throws Exception {
    LocalStorage storage = newStorage();
    FileStorage.StoredFile stored =
        storage.store("guides", "材料.docx", new ByteArrayInputStream("hello".getBytes()));
    assertTrue(Path.of(stored.path()).startsWith(tempDir));
    assertTrue(stored.sha256().matches("[0-9a-f]{64}"));
    assertEquals("hello", Files.readString(Path.of(stored.path())));
  }

  @Test
  void folderTraversalIsRejected() {
    LocalStorage storage = newStorage();
    assertThrows(
        Exception.class,
        () -> storage.store("../../etc", "passwd", new ByteArrayInputStream("x".getBytes())));
  }

  @Test
  void filenameTraversalIsSanitized() throws Exception {
    LocalStorage storage = newStorage();
    FileStorage.StoredFile stored =
        storage.store("uploads", "..\\..\\evil.pdf", new ByteArrayInputStream("x".getBytes()));
    assertTrue(Path.of(stored.path()).startsWith(tempDir));
    assertFalse(Path.of(stored.path()).toString().contains(".."));
  }

  @Test
  void deleteOnlyRemovesFilesUnderRoot() throws Exception {
    LocalStorage storage = newStorage();
    FileStorage.StoredFile stored =
        storage.store("tmp", "a.txt", new ByteArrayInputStream("x".getBytes()));
    storage.delete(stored.path());
    assertFalse(Files.exists(Path.of(stored.path())));

    // root 之外的路径静默忽略
    Path outside = Files.createTempFile("eaos-outside", ".txt");
    storage.delete(outside.toString());
    assertTrue(Files.exists(outside));
    Files.deleteIfExists(outside);
  }
}
