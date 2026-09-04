const jsonHeaders = { 'Content-Type': 'application/json' };

const TOKEN_KEY = 'eaos-token';
const REFRESH_KEY = 'eaos-refresh-token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(accessToken, refreshToken) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) {
    localStorage.setItem(REFRESH_KEY, refreshToken);
  }
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

function authHeaders(headers = {}) {
  const token = getToken();
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers;
}

let refreshingPromise = null;

async function tryRefresh() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }
  if (!refreshingPromise) {
    refreshingPromise = (async () => {
      try {
        const response = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: jsonHeaders,
          body: JSON.stringify({ refreshToken }),
        });
        const data = await response.json().catch(() => null);
        const payload = data?.code === 0 ? data.data : null;
        if (!response.ok || !payload?.token) {
          return false;
        }
        setTokens(payload.token, payload.refreshToken);
        return true;
      } catch {
        return false;
      } finally {
        refreshingPromise = null;
      }
    })();
  }
  return refreshingPromise;
}

function handleUnauthorized() {
  clearTokens();
  window.dispatchEvent(new Event('eaos-unauthorized'));
}

async function request(path, options = {}, retried = false) {
  const response = await fetch(path, { ...options, headers: authHeaders(options.headers) });
  if (response.status === 401 && !retried && !path.startsWith('/api/auth/')) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request(path, options, true);
    }
    handleUnauthorized();
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.detail?.message || data?.detail || data?.message || `请求失败：${response.status}`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return data;
}

function unwrapEnvelope(data) {
  return data?.code === 0 && Object.prototype.hasOwnProperty.call(data, 'data')
    ? data.data
    : data;
}

async function fetchFileBlob(path, retried = false) {
  const response = await fetch(path, { headers: authHeaders() });
  if (response.status === 401 && !retried && !path.startsWith('/api/auth/')) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return fetchFileBlob(path, true);
    }
    handleUnauthorized();
    throw new Error('登录已过期，请重新登录');
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `下载失败：${response.status}`);
  }
  return response.blob();
}

function nameFromPath(path) {
  return decodeURIComponent(String(path || '').split('/').filter(Boolean).pop() || 'file');
}

/** 受控下载：经 Java 鉴权端点以带令牌请求取回文件，触发浏览器保存。 */
export async function downloadFile(path, fallbackName) {
  const blob = await fetchFileBlob(path);
  const filename = fallbackName || nameFromPath(path);
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
}

/** 受控下载：返回 object URL，供 iframe/新窗口预览。 */
export async function openFileBlobUrl(path) {
  const blob = await fetchFileBlob(path);
  return URL.createObjectURL(blob);
}

export async function login(username, password) {
  const data = await request('/api/auth/login', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ username, password }),
  });
  const payload = unwrapEnvelope(data);
  if (payload?.token) {
    setTokens(payload.token, payload.refreshToken);
  }
  return payload;
}

export async function logout() {
  const refreshToken = getRefreshToken();
  if (refreshToken) {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ refreshToken }),
    }).catch(() => null);
  }
  clearTokens();
}

export async function changePassword(oldPassword, newPassword) {
  return unwrapEnvelope(await request('/api/auth/change-password', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ oldPassword, newPassword }),
  }));
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

export function fetchFactCheckReport(id) {
  return request(`/api/drafts/${encodeURIComponent(id)}/factcheck`);
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
  return request('/api/exports', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId, format }),
  });
}

export function fetchExportHistory(draftId) {
  const query = draftId ? `?draft_id=${encodeURIComponent(draftId)}` : '';
  return request(`/api/exports${query}`);
}

export function updateDraftStatus(draftId, status) {
  return request(`/api/drafts/${encodeURIComponent(draftId)}/status`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ status }),
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

export function searchMaterials(query, materialIds = [], limit = 6) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  if (materialIds.length) params.set('material_ids', materialIds.join(','));
  return request(`/api/materials/search?${params.toString()}`);
}

export function askPolicy(payload) {
  return request('/api/policy/chat', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function interpretPolicyClause(payload) {
  return request('/api/policy/interpret', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function checkPolicyCompliance(payload) {
  return request('/api/policy/compliance/check', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function searchPolicy(query, filters = {}) {
  const params = new URLSearchParams({ q: query, limit: String(filters.limit || 6) });
  if (filters.industry) params.set('industry', filters.industry);
  if (filters.level) params.set('level', filters.level);
  if (filters.authority) params.set('authority', filters.authority);
  return request(`/api/policy/search?${params.toString()}`);
}

export function fetchPolicyDocuments(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/policy/documents${query}`);
}

export function fetchIntelligenceItems(filters = {}) {
  const params = new URLSearchParams({
    page: String(filters.page || 1),
    page_size: String(filters.pageSize || 20),
  });
  if (filters.keyword) params.set('keyword', filters.keyword);
  if (filters.sourceId) params.set('source', String(filters.sourceId));
  return request(`/api/intelligence/items?${params.toString()}`);
}

export function fetchIntelligenceClusters(topic = '') {
  const params = new URLSearchParams({ limit: '50' });
  if (topic) params.set('topic', topic);
  return request(`/api/intelligence/clusters?${params.toString()}`);
}

export function summarizeIntelligence(payload) {
  return request('/api/intelligence/summarize', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export async function fetchIntelligenceReports(period = '') {
  const params = new URLSearchParams();
  if (period) params.set('period', period);
  const query = params.toString() ? `?${params.toString()}` : '';
  const response = await request(`/api/reports/intelligence${query}`);
  if (response && typeof response === 'object' && 'code' in response) {
    if (response.code !== 0) throw new Error(response.message || '获取情报简报失败');
    return response.data || [];
  }
  return response || [];
}

// ===== 舆情分析（P1）：Java 业务接口返回统一 R<T> 信封 =====
function unwrap(response) {
  if (response && typeof response === 'object' && 'code' in response) {
    if (response.code !== 0) throw new Error(response.message || '请求失败');
    return response.data;
  }
  return response;
}

// ===== P2 会议公开信息整理 =====
export function fetchMeetings(filters = {}) {
  const params = new URLSearchParams({
    page: String(filters.page || 1),
    pageSize: String(filters.pageSize || 20),
  });
  if (filters.status) params.set('status', filters.status);
  if (filters.keyword) params.set('keyword', filters.keyword);
  return request(`/api/meeting/conferences?${params.toString()}`).then(unwrap);
}

export function fetchMeetingDetail(id) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}`).then(unwrap);
}

export function createMeeting(payload) {
  return request('/api/meeting/conferences', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }).then(unwrap);
}

export function addMeetingLink(id, payload) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/link`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }).then(unwrap);
}

export function addMeetingTranscript(id, payload) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/transcript`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }).then(unwrap);
}

export function uploadMeetingMaterial(id, file) {
  const body = new FormData();
  body.append('file', file);
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body,
  }).then(unwrap);
}

export function deleteMeetingMaterial(id, materialId) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/materials/${encodeURIComponent(materialId)}`, {
    method: 'DELETE',
  }).then(unwrap);
}

export function organizeMeeting(id) {
  return request(`/api/meeting/conferences/${encodeURIComponent(id)}/organize`, { method: 'POST' }).then(unwrap);
}

export async function downloadMeetingReport(conferenceId, reportId, filename = '会议纪要.docx') {
  const response = await fetch(
    `/api/meeting/conferences/${encodeURIComponent(conferenceId)}/reports/${encodeURIComponent(reportId)}/export`,
    { headers: authHeaders() },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.message || data?.detail || `导出失败：${response.status}`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function fetchMeetingNotifications(page = 1, pageSize = 20) {
  return request(`/api/meeting/notifications?page=${page}&pageSize=${pageSize}`).then(unwrap);
}

export function fetchMeetingUnreadCount() {
  return request('/api/meeting/notifications/unread-count').then(unwrap);
}

export function markMeetingNotificationRead(id) {
  return request(`/api/meeting/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }).then(unwrap);
}

export function markAllMeetingNotificationsRead() {
  return request('/api/meeting/notifications/read-all', { method: 'POST' }).then(unwrap);
}

export function fetchOpinionMonitors() {
  return request('/api/opinion/monitors').then(unwrap);
}

export function fetchOpinionMonitor(id) {
  return request(`/api/opinion/monitors/${encodeURIComponent(id)}`).then(unwrap);
}

export function createOpinionMonitor(payload) {
  return request('/api/opinion/monitors', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) }).then(unwrap);
}

export function updateOpinionMonitor(id, payload) {
  return request(`/api/opinion/monitors/${encodeURIComponent(id)}`, { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(payload) }).then(unwrap);
}

export function deleteOpinionMonitor(id) {
  return request(`/api/opinion/monitors/${encodeURIComponent(id)}`, { method: 'DELETE' }).then(unwrap);
}

export function toggleOpinionMonitor(id) {
  return request(`/api/opinion/monitors/${encodeURIComponent(id)}/toggle`, { method: 'POST' }).then(unwrap);
}

export function triggerOpinionMonitor(id) {
  return request(`/api/opinion/collect/monitor/${encodeURIComponent(id)}`, { method: 'POST' }).then(unwrap);
}

export function fetchOpinionArticles(filters = {}) {
  const params = new URLSearchParams({
    page: String(filters.page || 1),
    pageSize: String(filters.pageSize || 20),
  });
  if (filters.monitorId) params.set('monitorId', String(filters.monitorId));
  if (filters.keyword) params.set('keyword', filters.keyword);
  return request(`/api/opinion/articles?${params.toString()}`).then(unwrap);
}

export function fetchOpinionArticle(id) {
  return request(`/api/opinion/articles/${encodeURIComponent(id)}`).then(unwrap);
}

export function fetchOpinionEvents(filters = {}) {
  const params = new URLSearchParams();
  if (filters.monitorId) params.set('monitorId', String(filters.monitorId));
  if (filters.riskLevel) params.set('riskLevel', filters.riskLevel);
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/events${query}`).then(unwrap);
}

export function fetchOpinionAnalysis(articleId) {
  return request(`/api/opinion/analysis/article/${encodeURIComponent(articleId)}`).then(unwrap);
}

export function reviewOpinionAnalysis(analysisId, payload) {
  return request(`/api/opinion/analysis/${encodeURIComponent(analysisId)}/review`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }).then(unwrap);
}

export function fetchOpinionCollectTasks(monitorId = '') {
  const query = monitorId ? `?monitorId=${encodeURIComponent(monitorId)}` : '';
  return request(`/api/opinion/collect/tasks${query}`).then(unwrap);
}

export function fetchOpinionAlerts(filters = {}) {
  const params = new URLSearchParams();
  if (filters.monitorId) params.set('monitorId', String(filters.monitorId));
  if (filters.state) params.set('state', filters.state);
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/alerts${query}`).then(unwrap);
}

export function handleOpinionAlert(id, payload) {
  return request(`/api/opinion/alerts/${encodeURIComponent(id)}/handle`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) }).then(unwrap);
}

export function fetchOpinionNotifications(alertId) {
  return request(`/api/opinion/alerts/${encodeURIComponent(alertId)}/notifications`).then(unwrap);
}

export function fetchOpinionReports(filters = {}) {
  const params = new URLSearchParams();
  if (filters.monitorId) params.set('monitorId', String(filters.monitorId));
  if (filters.period) params.set('period', filters.period);
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/reports${query}`).then(unwrap).then((reports) => (
    Array.isArray(reports) ? reports.map((report) => ({
      ...report,
      contentHtml: sanitizeOpinionHtml(report.contentHtml),
    })) : reports
  ));
}

const opinionHtmlTags = new Set(['H3', 'H4', 'P', 'UL', 'OL', 'LI', 'STRONG', 'EM', 'A',
  'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'BR']);

function sanitizeOpinionHtml(value) {
  if (typeof document === 'undefined') return '';
  const template = document.createElement('template');
  template.innerHTML = String(value || '');
  const visit = (node) => {
    [...node.children].forEach((child) => {
      if (!opinionHtmlTags.has(child.tagName)) {
        child.replaceWith(...child.childNodes);
        return;
      }
      [...child.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        const allowed = child.tagName === 'A' && ['href', 'target', 'rel'].includes(name);
        let safe = true;
        if (name === 'href') {
          try {
            safe = /^(https?:)$/i.test(new URL(attribute.value, window.location.href).protocol);
          } catch {
            safe = false;
          }
        }
        if (!allowed || (name === 'href' && !safe)) child.removeAttribute(attribute.name);
      });
      if (child.tagName === 'A') {
        child.setAttribute('target', '_blank');
        child.setAttribute('rel', 'noopener noreferrer');
      }
      visit(child);
    });
  };
  visit(template.content);
  return template.innerHTML;
}

export function generateOpinionReport(monitorId, period = 'daily') {
  return request(`/api/opinion/reports/generate?monitorId=${encodeURIComponent(monitorId)}&period=${encodeURIComponent(period)}`, { method: 'POST' }).then(unwrap);
}

export function publishOpinionReport(id) {
  return request(`/api/opinion/reports/${encodeURIComponent(id)}/publish`, { method: 'POST' }).then(unwrap);
}

export function exportOpinionReportPdf(id) {
  return request(`/api/opinion/reports/${encodeURIComponent(id)}/pdf`).then(unwrap);
}

export function generateOpinionSuggestion(targetType, targetId) {
  return request(`/api/opinion/suggestions/generate?targetType=${encodeURIComponent(targetType)}&targetId=${encodeURIComponent(targetId)}`, { method: 'POST' }).then(unwrap);
}

export function feedbackOpinionSuggestion(id, payload) {
  return request(`/api/opinion/suggestions/${encodeURIComponent(id)}/feedback`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) }).then(unwrap);
}

export function fetchOpinionSuggestions(targetType, targetId) {
  return request(`/api/opinion/suggestions?targetType=${encodeURIComponent(targetType)}&targetId=${encodeURIComponent(targetId)}`).then(unwrap);
}

export function fetchOpinionSpread(monitorId, verified) {
  const params = new URLSearchParams();
  if (monitorId) params.set('monitorId', String(monitorId));
  if (verified !== undefined && verified !== null && verified !== '') params.set('verified', verified);
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/spread${query}`).then(unwrap);
}

export function analyzeOpinionSpread(monitorId) {
  return request(`/api/opinion/spread/analyze?monitorId=${encodeURIComponent(monitorId)}`, { method: 'POST' }).then(unwrap);
}

export function fetchOpinionCases(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString() ? `?${params.toString()}` : '';
  return request(`/api/opinion/cases${query}`).then(unwrap);
}

async function qualRequest(path, options = {}) {
  const data = await request(path, options);
  return data?.data ?? data;
}

export function fetchQualGuides() {
  return qualRequest('/api/qual/guides');
}

export function uploadQualGuide(file, fields) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  return qualRequest('/api/qual/guides/upload', { method: 'POST', body: form });
}

export function fetchQualMaterials() {
  return qualRequest('/api/qual/materials');
}

export function uploadQualMaterial(file) {
  const form = new FormData();
  form.append('file', file);
  return qualRequest('/api/qual/materials/upload', { method: 'POST', body: form });
}

export function createQualTask(payload) {
  return qualRequest('/api/qual/tasks', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

export function fetchQualTasks() {
  return qualRequest('/api/qual/tasks');
}

export function fetchQualTask(id) {
  return qualRequest(`/api/qual/tasks/${encodeURIComponent(id)}`);
}

export function fetchQualReports(taskId) {
  return qualRequest(`/api/qual/tasks/${encodeURIComponent(taskId)}/reports`);
}

export function fetchQualDocument(id) {
  return qualRequest(`/api/qual/documents/${encodeURIComponent(id)}`);
}

export function saveQualDocument(id, content, changeNote = '') {
  return qualRequest(`/api/qual/documents/${encodeURIComponent(id)}/edit`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ content, changeNote }),
  });
}

export function fetchQualVersions(id) {
  return qualRequest(`/api/qual/documents/${encodeURIComponent(id)}/versions`);
}

export function rollbackQualDocument(id, versionNo) {
  return qualRequest(`/api/qual/documents/${encodeURIComponent(id)}/rollback`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ versionNo }),
  });
}

export function reviewQualDocument(id, action, comment = '') {
  return qualRequest(`/api/qual/documents/${encodeURIComponent(id)}/review/${action}`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ comment }),
  });
}

export async function downloadQualDocument(id) {
  const response = await fetch(`/api/qual/documents/${encodeURIComponent(id)}/export`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.message || data?.detail || `导出失败：${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = '资质申报材料初稿.docx';
  link.click();
  URL.revokeObjectURL(url);
}

export function subscribeQualTask(taskId, onEvent, onError) {
  // EventSource 无法携带 Authorization 头，改为 access_token 查询参数（后端 JwtAuthenticationFilter 支持）
  const token = getToken();
  const suffix = token ? `?access_token=${encodeURIComponent(token)}` : '';
  const source = new EventSource(`/api/qual/tasks/${encodeURIComponent(taskId)}/events${suffix}`);
  ['progress', 'partial', 'document', 'failed'].forEach((type) => {
    source.addEventListener(type, (event) => {
      try {
        onEvent(type, JSON.parse(event.data));
      } catch {
        onEvent(type, {});
      }
    });
  });
  source.onerror = (error) => {
    if (onError) onError(error);
  };
  return source;
}

// ---- 统一消息中心（站内信，覆盖会议/舆情/资质等全部类型） ----
export function fetchNotifications(page = 1, pageSize = 20, type = '') {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  if (type) query.set('type', type);
  return request(`/api/notifications?${query.toString()}`).then(unwrapEnvelope);
}

export function fetchUnreadCount() {
  return request('/api/notifications/unread-count').then(unwrapEnvelope);
}

export function markNotificationRead(id) {
  return request(`/api/notifications/${id}/read`, { method: 'POST' }).then(unwrapEnvelope);
}

export function markAllNotificationsRead(type = '') {
  const suffix = type ? `?type=${encodeURIComponent(type)}` : '';
  return request(`/api/notifications/read-all${suffix}`, { method: 'POST' }).then(unwrapEnvelope);
}

