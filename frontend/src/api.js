const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

export async function createSession(title = 'New session', token) {
  const r = await fetch(`${BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(`createSession ${r.status}`);
  return r.json();
}

export async function listSessions(token) {
  const r = await fetch(`${BASE}/api/sessions`, { headers: authHeaders(token) });
  if (!r.ok) throw new Error(`listSessions ${r.status}`);
  return r.json();
}

export async function getMessages(sessionId, token) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/messages`, {
    headers: authHeaders(token),
  });
  if (!r.ok) return [];
  return r.json();
}

export async function renameSession(sessionId, title, token) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(`renameSession ${r.status}`);
  return r.json();
}

export async function deleteSession(sessionId, token) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  });
  if (!r.ok) throw new Error(`deleteSession ${r.status}`);
}

export async function setupUser(email, token) {
  const r = await fetch(`${BASE}/api/users/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ email }),
  });
  if (!r.ok) throw new Error(`setupUser ${r.status}`);
  return r.json();
}

export async function getContacts(token) {
  const r = await fetch(`${BASE}/api/contacts`, { headers: authHeaders(token) });
  if (!r.ok) throw new Error(`getContacts ${r.status}`);
  return r.json();
}

export async function exportContacts(token) {
  const r = await fetch(`${BASE}/api/contacts/export`, { headers: authHeaders(token) });
  if (!r.ok) throw new Error(`exportContacts ${r.status}`);
  return r.blob();
}

export async function joinWaitlist(email) {
  const r = await fetch(`${BASE}/api/waitlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!r.ok) throw new Error(`joinWaitlist ${r.status}`);
  return r.json();
}

export async function uploadFile(sessionId, file, kind, token) {
  const form = new FormData();
  form.append('file', file);
  form.append('kind', kind);
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/upload`, {
    method: 'POST',
    headers: authHeaders(token),
    body: form,
  });
  if (!r.ok) throw new Error(`upload ${r.status}`);
  return r.json();
}
