const jsonHeaders = { 'Content-Type': 'application/json' };

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.detail?.message || data?.detail || data?.message || `请求失败：${response.status}`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return data;
}

export function fetchTemplates() {
  return request('/api/templates');
}

export function fetchStyles() {
  return request('/api/templates/styles');
}

export function fetchMaterials() {
  return request('/api/materials');
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

export function exportDraft(draftId, format) {
  return request('/api/drafts/export', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId, format }),
  });
}

export function reviseDraft(draftId, instruction) {
  return request('/api/drafts/revise', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ draftId, instruction }),
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
