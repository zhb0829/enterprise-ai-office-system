package com.eaos.admin.qual_doc;

import com.eaos.admin.common.R;
import com.eaos.admin.security.LoginUser;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/qual/admin")
@RequiredArgsConstructor
public class QualAdminController {

    private final QualDocService service;

    @Value("${eaos.security.enabled:false}")
    private boolean securityEnabled;

    @GetMapping("/enterprises")
    public R<?> enterprises(@AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.enterprises());
    }

    @GetMapping("/tasks")
    public R<?> tasks(@RequestParam(defaultValue = "") String owner,
                      @RequestParam(defaultValue = "") String status,
                      @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.adminTasks(owner, status));
    }

    @GetMapping("/tasks/{taskId}")
    public R<?> task(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.adminTask(taskId));
    }

    @GetMapping("/tasks/{taskId}/detail")
    public R<?> detail(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.adminTaskDetail(taskId));
    }

    @PutMapping("/tasks/{taskId}")
    public R<?> update(@PathVariable String taskId, @RequestBody QualDto.AdminTaskUpdateRequest request,
                       @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.adminUpdateTask(taskId, request));
    }

    @PostMapping("/tasks/{taskId}/archive")
    public R<?> archive(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.archiveTask(taskId));
    }

    @PostMapping("/tasks/{taskId}/restore")
    public R<?> restore(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.restoreTask(taskId));
    }

    @PostMapping("/tasks/{taskId}/retry")
    public R<?> retry(@PathVariable String taskId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.retryTask(taskId));
    }

    @PostMapping("/documents/{documentId}/unlock")
    public R<?> unlock(@PathVariable String documentId, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.unlockDocument(documentId, user == null ? "manual" : user.getUsername()));
    }

    @GetMapping("/enterprises/{owner}/materials")
    public R<?> ownerMaterials(@PathVariable String owner, @AuthenticationPrincipal LoginUser user) {
        requireAdmin(user);
        return R.ok(service.adminOwnerMaterials(owner));
    }

    private void requireAdmin(LoginUser user) {
        if (securityEnabled && (user == null || !"ADMIN".equalsIgnoreCase(user.getRole()))) {
            throw new IllegalArgumentException("仅系统管理员可执行该操作");
        }
    }
}
