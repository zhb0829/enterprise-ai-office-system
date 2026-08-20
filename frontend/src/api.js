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
