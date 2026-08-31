package com.eaos.admin.qual_doc;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class QualStateMachineServiceTest {

  private final QualStateMachineService stateMachine = new QualStateMachineService();

  @Test
  void happyPathTransitionsAreAllowed() {
    assertDoesNotThrow(
        () -> {
          stateMachine.assertTaskTransition(QualTaskStatus.CREATED, QualTaskStatus.PARSING);
          stateMachine.assertTaskTransition(QualTaskStatus.PARSING, QualTaskStatus.GENERATING);
          stateMachine.assertTaskTransition(QualTaskStatus.GENERATING, QualTaskStatus.VALIDATING);
          stateMachine.assertTaskTransition(QualTaskStatus.VALIDATING, QualTaskStatus.READY_REVIEW);
          stateMachine.assertDocumentTransition(
              QualDocumentStatus.DRAFT, QualDocumentStatus.IN_REVIEW);
          stateMachine.assertDocumentTransition(
              QualDocumentStatus.IN_REVIEW, QualDocumentStatus.APPROVED);
          stateMachine.assertDocumentTransition(
              QualDocumentStatus.APPROVED, QualDocumentStatus.LOCKED);
        });
  }

  @Test
  void skippingStatesIsRejected() {
    assertThrows(
        IllegalStateException.class,
        () -> stateMachine.assertTaskTransition(QualTaskStatus.CREATED, QualTaskStatus.VALIDATING));
    // LOCKED 只能回退到 APPROVED，不能直接进入 IN_REVIEW
    assertThrows(
        IllegalStateException.class,
        () ->
            stateMachine.assertDocumentTransition(
                QualDocumentStatus.LOCKED, QualDocumentStatus.IN_REVIEW));
  }

  @Test
  void failedTaskCanRetryOrArchive() {
    assertDoesNotThrow(
        () -> {
          stateMachine.assertTaskTransition(QualTaskStatus.FAILED, QualTaskStatus.PARSING);
          stateMachine.assertTaskTransition(QualTaskStatus.FAILED, QualTaskStatus.ARCHIVED);
        });
    assertThrows(
        IllegalStateException.class,
        () ->
            stateMachine.assertTaskTransition(QualTaskStatus.FAILED, QualTaskStatus.READY_REVIEW));
  }
}
