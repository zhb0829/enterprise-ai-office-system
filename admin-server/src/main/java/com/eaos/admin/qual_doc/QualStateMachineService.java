package com.eaos.admin.qual_doc;

import org.springframework.stereotype.Service;

import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;

@Service
public class QualStateMachineService {

    private static final Map<QualTaskStatus, EnumSet<QualTaskStatus>> TASK_TRANSITIONS = new EnumMap<>(QualTaskStatus.class);
    private static final Map<QualDocumentStatus, EnumSet<QualDocumentStatus>> DOCUMENT_TRANSITIONS = new EnumMap<>(QualDocumentStatus.class);

    static {
        TASK_TRANSITIONS.put(QualTaskStatus.CREATED, EnumSet.of(QualTaskStatus.PARSING, QualTaskStatus.FAILED));
        TASK_TRANSITIONS.put(QualTaskStatus.PARSING, EnumSet.of(QualTaskStatus.GENERATING, QualTaskStatus.FAILED));
        TASK_TRANSITIONS.put(QualTaskStatus.GENERATING, EnumSet.of(QualTaskStatus.VALIDATING, QualTaskStatus.FAILED));
        TASK_TRANSITIONS.put(QualTaskStatus.VALIDATING, EnumSet.of(QualTaskStatus.READY_REVIEW, QualTaskStatus.FAILED));
        TASK_TRANSITIONS.put(QualTaskStatus.READY_REVIEW, EnumSet.noneOf(QualTaskStatus.class));
        TASK_TRANSITIONS.put(QualTaskStatus.FAILED, EnumSet.of(QualTaskStatus.PARSING));

        DOCUMENT_TRANSITIONS.put(QualDocumentStatus.DRAFT, EnumSet.of(QualDocumentStatus.IN_REVIEW));
        DOCUMENT_TRANSITIONS.put(QualDocumentStatus.IN_REVIEW, EnumSet.of(QualDocumentStatus.APPROVED, QualDocumentStatus.DRAFT));
        DOCUMENT_TRANSITIONS.put(QualDocumentStatus.APPROVED, EnumSet.of(QualDocumentStatus.LOCKED));
        DOCUMENT_TRANSITIONS.put(QualDocumentStatus.LOCKED, EnumSet.noneOf(QualDocumentStatus.class));
    }

    public void assertTaskTransition(QualTaskStatus from, QualTaskStatus to) {
        if (from != to && !TASK_TRANSITIONS.getOrDefault(from, EnumSet.noneOf(QualTaskStatus.class)).contains(to)) {
            throw new IllegalStateException("不允许的资质任务状态迁移: " + from + " -> " + to);
        }
    }

    public void assertDocumentTransition(QualDocumentStatus from, QualDocumentStatus to) {
        if (from != to && !DOCUMENT_TRANSITIONS.getOrDefault(from, EnumSet.noneOf(QualDocumentStatus.class)).contains(to)) {
            throw new IllegalStateException("不允许的资质文档状态迁移: " + from + " -> " + to);
        }
    }
}
