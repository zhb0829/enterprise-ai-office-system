package com.eaos.admin.opinion.support;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Objects;

/** Centralizes monitor ownership checks for user-facing opinion data. */
@Service
@RequiredArgsConstructor
public class OpinionAccessService {

    private final OpinionMonitorMapper monitorMapper;

    public OpinionMonitor requireMonitor(Long monitorId) {
        if (monitorId == null) {
            throw new IllegalArgumentException("monitorId 不能为空");
        }
        OpinionMonitor monitor = monitorMapper.selectById(monitorId);
        if (monitor == null) {
            throw new IllegalArgumentException("监控任务不存在");
        }
        if (OpinionCurrentUser.isAuthenticated() && !OpinionCurrentUser.isAdmin()
                && !Objects.equals(monitor.getUserId(), OpinionCurrentUser.id())) {
            throw new IllegalArgumentException("无权访问该监控任务");
        }
        return monitor;
    }

    public List<Long> visibleMonitorIds() {
        if (!OpinionCurrentUser.isAuthenticated() || OpinionCurrentUser.isAdmin()) {
            return List.of();
        }
        return monitorMapper.selectList(Wrappers.<OpinionMonitor>lambdaQuery()
                        .eq(OpinionMonitor::getUserId, OpinionCurrentUser.id()))
                .stream().map(OpinionMonitor::getId).toList();
    }

    public void requireAdmin() {
        if (!OpinionCurrentUser.isAdmin()) {
            throw new IllegalArgumentException("仅系统管理员可执行该操作");
        }
    }
}
