import { useRef, useState } from 'react';
import { useClerk, useUser } from '@clerk/clerk-react';

function relTime(iso) {
  const m = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function initials(name, email) {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : parts[0].slice(0, 2).toUpperCase();
  }
  return email ? email[0].toUpperCase() : '?';
}

export default function Sidebar({
  sessions, activeId, onSelect, onNew, onRename, onDelete,
  activeTab, onTabChange, scanCount,
}) {
  const { signOut } = useClerk();
  const { user }   = useUser();
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef(null);

  function startEdit(e, s) {
    e.stopPropagation();
    setEditingId(s.session_id);
    setEditValue(s.title);
    setTimeout(() => { inputRef.current?.select(); }, 0);
  }

  function commitEdit(s) {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== s.title) onRename(s.session_id, trimmed);
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

  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || 'Account';
  const avatarUrl   = user?.imageUrl;
  const isFull      = scanCount >= 2;

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-brand">CardSync</span>
        <div className="sidebar-header-actions">
          {activeTab === 'chats' && (
            <button className="btn-new" onClick={onNew}>+ New</button>
          )}
        </div>
      </div>

      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab${activeTab === 'chats' ? ' active' : ''}`}
          onClick={() => onTabChange('chats')}
        >Chats</button>
        <button
          className={`sidebar-tab${activeTab === 'contacts' ? ' active' : ''}`}
          onClick={() => onTabChange('contacts')}
        >Contacts</button>
      </div>

      {activeTab === 'chats' && (
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
      )}

      <div className="sidebar-footer">
        <div className={`scan-counter${isFull ? ' scan-counter--full' : ''}`}>
          <div className="scan-dots">
            <span className={`scan-dot${scanCount >= 1 ? ' used' : ''}${isFull ? ' full' : ''}`} />
            <span className={`scan-dot${scanCount >= 2 ? ' used' : ''}${isFull ? ' full' : ''}`} />
          </div>
          <span className="scan-label">{scanCount} / 2 free scans used</span>
        </div>

        <div className="sidebar-profile">
          <div className="profile-avatar">
            {avatarUrl
              ? <img src={avatarUrl} alt="" className="profile-img" />
              : <span className="profile-initials">{initials(user?.fullName, user?.primaryEmailAddress?.emailAddress)}</span>
            }
          </div>
          <div className="profile-info">
            <span className="profile-name" title={displayName}>{displayName}</span>
          </div>
          <button className="btn-signout" onClick={() => signOut()}>Sign out</button>
        </div>
      </div>
    </aside>
  );
}
