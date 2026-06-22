import { useState, useRef } from 'react';

function relTime(iso) {
  const m = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onRename, onDelete }) {
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef(null);

  function startEdit(e, s) {
    e.stopPropagation();
    setEditingId(s.session_id);
    setEditValue(s.title);
    // Focus after render.
    setTimeout(() => { inputRef.current?.select(); }, 0);
  }

  function commitEdit(s) {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== s.title) {
      onRename(s.session_id, trimmed);
    }
    setEditingId(null);
  }

  function handleEditKey(e, s) {
    if (e.key === 'Enter')  { e.preventDefault(); commitEdit(s); }
    if (e.key === 'Escape') { setEditingId(null); }
  }

  function handleDelete(e, sessionId) {
    e.stopPropagation();
    if (window.confirm('Delete this session? This cannot be undone.')) {
      onDelete(sessionId);
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-brand">CardSync</span>
        <button className="btn-new" onClick={onNew}>+ New</button>
      </div>
      <nav className="session-list">
        {sessions.map(s => (
          <div
            key={s.session_id}
            className={`session-item${s.session_id === activeId ? ' active' : ''}`}
            onClick={() => { if (editingId !== s.session_id) onSelect(s.session_id); }}
          >
            <div className="session-item-body">
              {editingId === s.session_id ? (
                <input
                  ref={inputRef}
                  className="session-title-input"
                  value={editValue}
                  onChange={e => setEditValue(e.target.value)}
                  onBlur={() => commitEdit(s)}
                  onKeyDown={e => handleEditKey(e, s)}
                  onClick={e => e.stopPropagation()}
                />
              ) : (
                <span
                  className="session-item-title"
                  onClick={e => startEdit(e, s)}
                  title="Click to rename"
                >
                  {s.title}
                </span>
              )}
              <span className="session-item-meta">{relTime(s.created_at)}</span>
            </div>
            <button
              className="session-delete-btn"
              title="Delete session"
              onClick={e => handleDelete(e, s.session_id)}
            >✕</button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
