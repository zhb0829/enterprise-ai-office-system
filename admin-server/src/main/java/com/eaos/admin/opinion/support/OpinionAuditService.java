package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.entity.OpinionAuditLog;
import com.eaos.admin.opinion.mapper.OpinionAuditLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.Map;

/** 审计日志写入。仅负责追加，不做业务判断。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionAuditService {

    private final OpinionAuditLogMapper auditLogMapper;

    public void record(String action, String targetType, Long targetId,
                       Map<String, Object> detail, String traceId) {
        try {
            OpinionAuditLog audit = new OpinionAuditLog();
            audit.setUserId(OpinionCurrentUser.id());
            audit.setAction(action);
            audit.setTargetType(targetType);
            audit.setTargetId(targetId);
            audit.setDetail(detail == null ? Map.of() : detail);
            audit.setTraceId(traceId == null ? "" : traceId);
            auditLogMapper.insert(audit);
        } catch (Exception e) {
            log.warn("写入舆情审计日志失败 action={} target={}:{}", action, targetType, targetId, e.getMessage());
        }
    }
}
