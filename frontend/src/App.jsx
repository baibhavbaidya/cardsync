import { useState, useEffect, useRef } from 'react';
import { useAuth, useUser } from '@clerk/clerk-react';
import { createSession, listSessions, renameSession, deleteSession, setupUser } from './api';
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';
import ContactsView from './components/ContactsView';

export default function App() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [scanCount, setScanCount] = useState(0);
  const [activeTab, setActiveTab] = useState('chats');

  // Guard against StrictMode's intentional double-invoke: refs survive the
  // artificial unmount/remount, so the second effect call sees true and exits.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function init() {
    const token = await getToken();
    const email = user?.primaryEmailAddress?.emailAddress ?? '';

    // Register or retrieve the user profile. Idempotent.
    if (email) {
      try {
        const profile = await setupUser(email, token);
        setScanCount(profile.scan_count);
      } catch (err) {
        console.error('User setup failed:', err);
      }
    }

    let list = [];
    try { list = await listSessions(token); } catch { /* backend not ready yet */ }

    if (list.length === 0) {
      const s = await createSession('New session', token);
      setSessions([s]);
      setActiveId(s.session_id);
    } else {
      setSessions(list);
      setActiveId(list[0].session_id);
    }
  }

  async function refreshScanCount() {
    const token = await getToken();
    const email = user?.primaryEmailAddress?.emailAddress ?? '';
    if (!email) return;
    try {
      const profile = await setupUser(email, token);
      setScanCount(profile.scan_count);
    } catch (err) {
      console.error('refreshScanCount failed:', err);
    }
  }

  async function handleNew() {
    const token = await getToken();
    const s = await createSession('New session', token);
    setSessions(prev => [s, ...prev]);
    setActiveId(s.session_id);
    setActiveTab('chats');
  }

  async function handleRename(sessionId, newTitle) {
    const token = await getToken();
    await renameSession(sessionId, newTitle, token);
    setSessions(prev => prev.map(s =>
      s.session_id === sessionId ? { ...s, title: newTitle } : s
    ));
  }

  async function handleDelete(sessionId) {
    const token = await getToken();
    await deleteSession(sessionId, token);
    setSessions(prev => {
      const next = prev.filter(s => s.session_id !== sessionId);
      if (activeId === sessionId) {
        setActiveId(next.length > 0 ? next[0].session_id : null);
      }
      return next;
    });
  }

  const active = sessions.find(s => s.session_id === activeId) ?? null;
  const userEmail = user?.primaryEmailAddress?.emailAddress ?? '';

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onRename={handleRename}
        onDelete={handleDelete}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        scanCount={scanCount}
      />
      {activeTab === 'contacts' ? (
        <ContactsView />
      ) : (
        active && (
          <ChatWindow
            key={activeId}
            session={active}
            onRename={handleRename}
            userEmail={userEmail}
            onScanComplete={refreshScanCount}
          />
        )
      )}
    </div>
  );
}
