const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export async function createSession(title = 'New session') {
  const r = await fetch(`${BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(`createSession ${r.status}`);
  return r.json();
}

export async function listSessions() {
  const r = await fetch(`${BASE}/api/sessions`);
  if (!r.ok) throw new Error(`listSessions ${r.status}`);
  return r.json();
}

export async function getMessages(sessionId) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/messages`);
  if (!r.ok) return [];
  return r.json();
}

export async function renameSession(sessionId, title) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(`renameSession ${r.status}`);
  return r.json();
}

export async function deleteSession(sessionId) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`deleteSession ${r.status}`);
}

export async function uploadFile(sessionId, file, kind) {
  const form = new FormData();
  form.append('file', file);
  form.append('kind', kind);
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/upload`, {
    method: 'POST',
    body: form,
  });
  if (!r.ok) throw new Error(`upload ${r.status}`);
  return r.json();
}
