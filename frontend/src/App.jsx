import { useState, useEffect, useRef } from 'react';
import { createSession, listSessions, renameSession, deleteSession } from './api';
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);

  // Guard against StrictMode's intentional double-invoke: refs survive the
  // artificial unmount/remount, so the second effect call sees true and exits.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    init();
  }, []);

  async function init() {
    let list = [];
    try { list = await listSessions(); } catch { /* backend not ready yet */ }

    if (list.length === 0) {
      const s = await createSession();
      setSessions([s]);
      setActiveId(s.session_id);
    } else {
      setSessions(list);
      setActiveId(list[0].session_id);
    }
  }

  async function handleNew() {
    const s = await createSession();
    setSessions(prev => [s, ...prev]);
    setActiveId(s.session_id);
  }

  async function handleRename(sessionId, newTitle) {
    await renameSession(sessionId, newTitle);
    setSessions(prev => prev.map(s =>
      s.session_id === sessionId ? { ...s, title: newTitle } : s
    ));
  }

  async function handleDelete(sessionId) {
    await deleteSession(sessionId);
    setSessions(prev => {
      const next = prev.filter(s => s.session_id !== sessionId);
      if (activeId === sessionId) {
        setActiveId(next.length > 0 ? next[0].session_id : null);
      }
      return next;
    });
  }

  const active = sessions.find(s => s.session_id === activeId) ?? null;

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onRename={handleRename}
        onDelete={handleDelete}
      />
      {active && <ChatWindow key={activeId} session={active} onRename={handleRename} />}
    </div>
  );
}
