const jsonHeaders = { 'Content-Type': 'application/json' };

const TOKEN_KEY = 'eaos-token';

function authHeaders(headers = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers;
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: authHeaders(options.headers) });
  const data = await response.json().catch(() => null);
  const message = data?.detail?.message || data?.detail || data?.message || `请求失败：${response.status}`;
  const isAuthenticationFailure = response.status === 401 || (
    response.status === 403
    && typeof message === 'string'
    && /无权限|未认证|登录|token|jwt/i.test(message)
  );
  if (isAuthenticationFailure) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event('eaos-unauthorized'));
  }
  if (!response.ok) {
    if (isAuthenticationFailure) {
      throw new Error('登录状态已失效或没有访问权限，请重新登录后再上传。');
    }
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  // 管理端 API 使用统一 R<T> 信封；Python 网关接口则直接返回业务数据。
  return data?.code === 0 && Object.prototype.hasOwnProperty.call(data, 'data') ? data.data : data;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function login(username, password) {
  return request('/api/auth/login', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ username, password }),
  });
}

export function fetchTemplates() {
  return request('/api/templates');
}

export function createTemplate(payload) {
  return request('/api/templates', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function toggleTemplate(id) {
  return request(`/api/templates/${encodeURIComponent(id)}/toggle`, {
    method: 'POST',
  });
}

export function fetchStyles() {
  return request('/api/templates/styles');
}

export function saveStyles(payload) {
  return request('/api/templates/styles', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function fetchMaterials() {
  return request('/api/materials');
}

export function fetchMaterial(id) {
  return request(`/api/materials/${encodeURIComponent(id)}`);
}

export function deleteMaterial(id) {
  return request(`/api/materials/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function createDraft(payload) {
  return request('/api/drafts/news', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function fetchDraft(id) {
  return request(`/api/drafts/${encodeURIComponent(id)}`);
}

export function fetchVersions(id) {
  return request(`/api/drafts/${encodeURIComponent(id)}/versions`);
}

export async function createDraftStream(payload, onEvent) {
  const response = await fetch('/api/drafts/news/stream', {
    method: 'POST',
    headers: authHeaders(jsonHeaders),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const message = data?.detail?.message || data?.detail || data?.message || `请求失败：${response.status}`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        // 忽略格式异常的事件
      }
    }
  }
}

export function exportDraft(draftId, format) {
  return request('/api/drafts/export', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId, format }),
  });
}

export function editDraftContent(draftId, content) {
  return request(`/api/drafts/${encodeURIComponent(draftId)}/edit`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ content }),
  });
}

export function reviseDraft(draftId, instruction) {
  return request('/api/drafts/revise', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId, instruction }),
  });
}

export function polishDraft(draftId) {
  return request('/api/drafts/polish', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId }),
  });
}

export function revertDraft(draftId, targetId) {
  return request(`/api/drafts/${encodeURIComponent(draftId)}/revert`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ targetId }),
  });
}

export function uploadMaterial(file) {
  const form = new FormData();
  form.append('file', file);
  return request('/api/materials/upload', {
    method: 'POST',
    body: form,
  });
}

export function fetchPolicyDocuments(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/policy/documents${query}`);
}

export function uploadPolicyDocument(file, fields = {}) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => {
    if (value) form.append(key, value);
  });
  return request('/api/policy/documents/upload', { method: 'POST', body: form });
}

export function collectPolicyUrl(payload) {
  return request('/api/policy/documents/from-url', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function updatePolicyDocumentStatus(id, status) {
  return request(`/api/policy/documents/${encodeURIComponent(id)}/status?status=${encodeURIComponent(status)}`, {
    method: 'POST',
  });
}

export function fetchIntelligenceSources() {
  return request('/api/sources');
}

export function createIntelligenceSource(payload) {
  return request('/api/sources', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function toggleIntelligenceSource(id) {
  return request(`/api/sources/${encodeURIComponent(id)}/toggle`, { method: 'POST' });
}

export function runIntelligenceSource(id) {
  return request(`/api/sources/${encodeURIComponent(id)}/run`, { method: 'POST' });
}

export function fetchIntelligenceTasks(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/intelligence/tasks${query}`);
}

export function retryIntelligenceTask(id) {
  return request(`/api/intelligence/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST' });
}

export function fetchIntelligenceReports(period = '') {
  const query = period ? `?period=${encodeURIComponent(period)}` : '';
  return request(`/api/reports/intelligence${query}`);
}

export function generateIntelligenceReport(period = 'daily') {
  return request('/api/reports/intelligence/generate', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ period }),
  });
}

// ===== P1 舆情分析：采集源治理与授权审核（管理端） =====
export function fetchOpinionSources(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/sources${query}`);
}

export function createOpinionSource(payload) {
  return request('/api/opinion/sources', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function updateOpinionSource(id, payload) {
  return request(`/api/opinion/sources/${encodeURIComponent(id)}`, { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function deleteOpinionSource(id) {
  return request(`/api/opinion/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function toggleOpinionSource(id) {
  return request(`/api/opinion/sources/${encodeURIComponent(id)}/toggle`, { method: 'POST' });
}

export function auditOpinionSource(id, payload) {
  return request(`/api/opinion/sources/${encodeURIComponent(id)}/audit`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function runOpinionSource(id, monitorId = '') {
  const query = monitorId ? `?monitorId=${encodeURIComponent(monitorId)}` : '';
  return request(`/api/opinion/collect/source/${encodeURIComponent(id)}${query}`, { method: 'POST' });
}

export function fetchOpinionCollectTasks(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/collect/tasks${query}`);
}

// ===== P1 舆情分析：告警规则 / 历史案例（管理端） =====
export function fetchOpinionAlertRules(monitorId = '') {
  const query = monitorId ? `?monitorId=${encodeURIComponent(monitorId)}` : '';
  return request(`/api/opinion/alert-rules${query}`);
}

export function createOpinionAlertRule(payload) {
  return request('/api/opinion/alert-rules', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function updateOpinionAlertRule(id, payload) {
  return request(`/api/opinion/alert-rules/${encodeURIComponent(id)}`, { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function deleteOpinionAlertRule(id) {
  return request(`/api/opinion/alert-rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function toggleOpinionAlertRule(id) {
  return request(`/api/opinion/alert-rules/${encodeURIComponent(id)}/toggle`, { method: 'POST' });
}

export function fetchOpinionCases(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/cases${query}`);
}

export function createOpinionCase(payload) {
  return request('/api/opinion/cases', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function updateOpinionCase(id, payload) {
  return request(`/api/opinion/cases/${encodeURIComponent(id)}`, { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function deleteOpinionCase(id) {
  return request(`/api/opinion/cases/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function fetchOpinionMonitors() {
  return request('/api/opinion/monitors');
}

export function fetchOpinionAlerts(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/alerts${query}`);
}

export function fetchOpinionReports(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/reports${query}`);
}

export function generateOpinionReport(monitorId, period = 'daily') {
  return request(`/api/opinion/reports/generate?monitorId=${encodeURIComponent(monitorId)}&period=${encodeURIComponent(period)}`, { method: 'POST' });
}

export function fetchQualGuides() {
  return request('/api/qual/guides');
}

export function uploadQualGuide(file, fields) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  return request('/api/qual/guides/upload', { method: 'POST', body: form });
}

export function fetchQualValidationRules() {
  return request('/api/qual/validation-rules');
}

export function saveQualValidationRule(payload) {
  return request('/api/qual/validation-rules', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function fetchAdminEnterprises() {
  return request('/api/qual/admin/enterprises');
}

export function fetchAdminQualTasks(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/qual/admin/tasks${query}`);
}

export function fetchAdminQualTaskDetail(taskId) {
  return request(`/api/qual/admin/tasks/${encodeURIComponent(taskId)}/detail`);
}

export function updateAdminQualTask(taskId, payload) {
  return request(`/api/qual/admin/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PUT',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function archiveAdminQualTask(taskId) {
  return request(`/api/qual/admin/tasks/${encodeURIComponent(taskId)}/archive`, { method: 'POST' });
}

export function restoreAdminQualTask(taskId) {
  return request(`/api/qual/admin/tasks/${encodeURIComponent(taskId)}/restore`, { method: 'POST' });
}

export function retryAdminQualTask(taskId) {
  return request(`/api/qual/admin/tasks/${encodeURIComponent(taskId)}/retry`, { method: 'POST' });
}

export function unlockAdminQualDocument(documentId) {
  return request(`/api/qual/admin/documents/${encodeURIComponent(documentId)}/unlock`, { method: 'POST' });
}

export function fetchAdminOwnerMaterials(owner) {
  return request(`/api/qual/admin/enterprises/${encodeURIComponent(owner)}/materials`);
}

// ===== P2 会议公开信息整理 =====
export function fetchAdminMeetings(filters = {}) {
  const params = new URLSearchParams({
    page: String(filters.page || 1),
    pageSize: String(filters.pageSize || 100),
  });
  if (filters.status) params.set('status', filters.status);
  if (filters.keyword) params.set('keyword', filters.keyword);
  if (filters.archived !== undefined && filters.archived !== '') params.set('archived', String(filters.archived));
  return request(`/api/meeting/conferences?${params.toString()}`);
}

export function fetchAdminMeetingDetail(id) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}`);
}

export function createAdminMeeting(payload) {
  return request('/api/meeting/conferences', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export function updateAdminMeeting(id, payload) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: jsonHeaders, body: JSON.stringify(payload),
  });
}

export function deleteAdminMeeting(id) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function archiveAdminMeeting(id, archived = true) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/archive?archived=${archived}`, { method: 'POST' });
}

export function addAdminMeetingLink(id, payload) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/link`, {
    method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload),
  });
}

export function addAdminMeetingTranscript(id, payload) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/transcript`, {
    method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload),
  });
}

export function uploadAdminMeetingMaterial(id, file) {
  const form = new FormData();
  form.append('file', file);
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/upload`, { method: 'POST', body: form });
}

export function deleteAdminMeetingMaterial(id, materialId) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/${encodeURIComponent(materialId)}`, {
    method: 'DELETE',
  });
}

export function organizeAdminMeeting(id) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/organize`, { method: 'POST' });
}

export function retryAdminMeetingTask(id, taskId) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskId)}/retry`, {
    method: 'POST',
  });
}
