const jsonHeaders = { 'Content-Type': 'application/json' };

const TOKEN_KEY = 'eaos-token';

function authHeaders(headers = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers;
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: authHeaders(options.headers) });
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event('eaos-unauthorized'));
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.detail?.message || data?.detail || data?.message || `请求失败：${response.status}`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return data;
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
