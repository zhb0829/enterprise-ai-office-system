package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.dto.OpinionSourceRequest;
import com.eaos.admin.opinion.dto.SourceAuditRequest;
import com.eaos.admin.opinion.entity.OpinionSource;
import com.eaos.admin.opinion.mapper.OpinionSourceMapper;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import com.eaos.admin.opinion.support.OpinionUrlPolicy;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class OpinionSourceService {

    private final OpinionSourceMapper sourceMapper;
    private final OpinionAuditService auditService;

    @Value("${eaos.security.enabled:false}")
    private boolean securityEnabled;

    public List<OpinionSource> list(String auditStatus, String status) {
        requireAdmin(OpinionCurrentUser.isAdmin());
        LambdaQueryWrapper<OpinionSource> wrapper = Wrappers.lambdaQuery();
        if (auditStatus != null && !auditStatus.isBlank()) {
            wrapper.eq(OpinionSource::getAuditStatus, auditStatus);
        }
        if (status != null && !status.isBlank()) {
            wrapper.eq(OpinionSource::getStatus, status);
        }
        return sourceMapper.selectList(wrapper.orderByDesc(OpinionSource::getCreatedAt));
    }

    public OpinionSource get(Long id) {
        requireAdmin(OpinionCurrentUser.isAdmin());
        OpinionSource source = sourceMapper.selectById(id);
        if (source == null) {
            throw new IllegalArgumentException("采集源不存在");
        }
        return source;
    }

    public OpinionSource create(OpinionSourceRequest request, boolean admin) {
        requireAdmin(admin);
        OpinionSource source = new OpinionSource();
        apply(source, request);
        source.setHealthStatus("unknown");
        source.setFailureCount(0);
        source.setAuditStatus("pending");
        source.setCreatedBy(OpinionCurrentUser.username());
        sourceMapper.insert(source);
        auditService.record("SOURCE_CREATE", "opinion_source", source.getId(),
                Map.of("name", source.getName(), "homepage", source.getHomepage()), null);
        return source;
    }

    public OpinionSource update(Long id, OpinionSourceRequest request, boolean admin) {
        requireAdmin(admin);
        OpinionSource source = get(id);
        apply(source, request);
        source.setUpdatedAt(LocalDateTime.now());
        sourceMapper.updateById(source);
        auditService.record("SOURCE_UPDATE", "opinion_source", id,
                Map.of("name", source.getName()), null);
        return source;
    }

    public void delete(Long id, boolean admin) {
        requireAdmin(admin);
        OpinionSource source = get(id);
        sourceMapper.deleteById(id);
        auditService.record("SOURCE_DELETE", "opinion_source", id,
                Map.of("name", source.getName()), null);
    }

    public OpinionSource toggle(Long id, boolean admin) {
        requireAdmin(admin);
        OpinionSource source = get(id);
        source.setStatus("enabled".equalsIgnoreCase(source.getStatus()) ? "disabled" : "enabled");
        source.setUpdatedAt(LocalDateTime.now());
        sourceMapper.updateById(source);
        return source;
    }

    public OpinionSource audit(Long id, SourceAuditRequest request, boolean admin) {
        requireAdmin(admin);
        OpinionSource source = get(id);
        String auditStatus = request.getAuditStatus();
        if (!List.of("approved", "rejected", "pending").contains(auditStatus)) {
            throw new IllegalArgumentException("审核状态必须为 approved/rejected/pending");
        }
        if ("approved".equals(auditStatus) && source.getAuthExpire() != null
                && source.getAuthExpire().isBefore(LocalDateTime.now())) {
            throw new IllegalArgumentException("授权已到期，无法审批通过");
        }
        source.setAuditStatus(auditStatus);
        source.setAuditNote(request.getAuditNote());
        source.setAuditBy(OpinionCurrentUser.username());
        source.setAuditAt(LocalDateTime.now());
        source.setUpdatedAt(LocalDateTime.now());
        sourceMapper.updateById(source);
        auditService.record("SOURCE_AUDIT", "opinion_source", id,
                Map.of("auditStatus", auditStatus, "note", request.getAuditNote()), null);
        return source;
    }

    private void apply(OpinionSource source, OpinionSourceRequest request) {
        source.setName(request.getName().trim());
        source.setSourceType(request.getSourceType());
        source.setPlatform(nullToEmpty(request.getPlatform()));
        source.setHomepage(OpinionUrlPolicy.validatePublicHttpUrl(request.getHomepage()));
        source.setAuthSubject(nullToEmpty(request.getAuthSubject()));
        source.setAuthScope(nullToEmpty(request.getAuthScope()));
        source.setAuthStart(request.getAuthStart());
        source.setAuthExpire(request.getAuthExpire());
        source.setCollectMethod(nullToEmpty(request.getCollectMethod()));
        source.setFrequency(nullToEmpty(request.getFrequency()));
        source.setRateLimit(nullToEmpty(request.getRateLimit()));
        source.setPriority(request.getPriority() == null ? 0 : request.getPriority());
        source.setAdapterVersion(nullToEmpty(request.getAdapterVersion()));
        source.setStatus(nullToEmpty(request.getStatus()));
    }

    private void requireAdmin(boolean admin) {
        if (securityEnabled && !admin) {
            throw new IllegalArgumentException("仅系统管理员可管理采集源");
        }
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value.trim();
    }
}
