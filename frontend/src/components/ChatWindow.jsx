import { useState, useEffect, useRef } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { getMessages, uploadFile, joinWaitlist } from '../api';
import { openSocket } from '../socket';
import Message from './Message';
import ConfirmCard from './ConfirmCard';
import Composer from './Composer';

let _id = 0;
const uid = () => ++_id;

export default function ChatWindow({ session, onRename, userEmail, onScanComplete }) {
  const { getToken } = useAuth();
  const [messages, setMessages]         = useState([]);
  const [streaming, setStreaming]       = useState('');
  const [busy, setBusy]                 = useState(false);
  const [interrupt, setInterrupt]       = useState(null);
  const [wsState, setWsState]           = useState('connecting');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue]     = useState('');
  const [limitReached, setLimitReached] = useState(false);
  const [showLimitModal, setShowLimitModal] = useState(false);
  const [waitlistEmail, setWaitlistEmail]   = useState('');
  const [waitlistStatus, setWaitlistStatus] = useState(null); // null | 'sending' | 'joined' | 'error'

  // Ref holds the latest streaming text so WebSocket handlers never read stale state.
  const streamRef      = useRef('');
  const socketRef      = useRef(null);
  const bottomRef      = useRef(null);
  const confirmCardRef = useRef(null);
  const composerRef    = useRef(null);
  const titleInputRef  = useRef(null);

  // Load persisted message history.
  useEffect(() => {
    getToken().then(token =>
      getMessages(session.session_id, token).then(msgs => {
        setMessages(msgs.map(m => ({
          id: uid(),
          type: m.role === 'user' ? 'user' : 'ai',
          content: m.content,
          mediaUrl: m.media_url,
          mediaKind: m.type !== 'text' ? m.type : null,
        })));
      }).catch(() => {})
    );
  }, [session.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Open WebSocket once per session. Token is fetched async then the socket is
  // created. The `ignore` flag prevents a discarded (StrictMode) effect from
  // touching state after its cleanup runs.
  useEffect(() => {
    let ignore = false;

    (async () => {
      const token = await getToken();
      if (ignore) return;
      const sock = openSocket(session.session_id, token, {
        onOpen:  () => { if (!ignore) setWsState('open'); },
        onClose: () => { if (!ignore) setWsState('closed'); },
        onEvent: (event) => { if (!ignore) handleEvent(event); },
      });
      socketRef.current = sock;
    })();

    return () => {
      ignore = true;
      socketRef.current?.closeWhenReady();
    };
  }, [session.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to latest message or streaming token.
  useEffect(() => {
    const t = setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    return () => clearTimeout(t);
  }, [messages, streaming]);

  // When the confirmation card appears, scroll its bottom edge into view so the
  // action buttons are visible regardless of transcript length.
  useEffect(() => {
    if (!interrupt) return;
    const t = setTimeout(
      () => confirmCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }),
      100,
    );
    return () => clearTimeout(t);
  }, [interrupt]);

  // handleEvent only touches refs and stable state setters — safe to capture once.
  function handleEvent(event) {
    console.log('WS EVENT:', JSON.stringify(event));
    if (event.type === 'token') {
      streamRef.current += event.data;
      setStreaming(streamRef.current);

    } else if (event.type === 'tool') {
      setMessages(prev => {
        const idx = prev.findLastIndex(
          m => m.type === 'tool' && m.name === event.data.name && m.status === 'running'
        );
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], status: event.data.status };
          return next;
        }
        return [...prev, { id: uid(), type: 'tool', name: event.data.name, status: event.data.status }];
      });

    } else if (event.type === 'interrupt') {
      flushStream();
      setInterrupt(event.data);
      setBusy(false);

    } else if (event.type === 'done') {
      flushStream();
      setInterrupt(null);
      setBusy(false);
      onScanComplete?.();

    } else if (event.type === 'limit_reached') {
      flushStream();
      setLimitReached(true);
      setShowLimitModal(true);
      setWaitlistEmail(userEmail);
      setWaitlistStatus(null);
      setBusy(false);

    } else if (event.type === 'error') {
      flushStream();
      setMessages(prev => [...prev, { id: uid(), type: 'ai', content: `Error: ${event.data}` }]);
      setInterrupt(null);
      setBusy(false);
    }
  }

  function flushStream() {
    const text = streamRef.current.trim();
    if (text) setMessages(prev => [...prev, { id: uid(), type: 'ai', content: text }]);
    streamRef.current = '';
    setStreaming('');
  }

  async function send({ text, imageFile, audioFile }) {
    if (busy) return;
    if (imageFile && limitReached) { setShowLimitModal(true); return; }
    // Reset streaming accumulator for the new turn.
    streamRef.current = '';
    setStreaming('');
    setBusy(true);

    const token = await getToken();
    let imageKey = null;
    let audioKey = null;
    const userMsg = { id: uid(), type: 'user', content: null, mediaUrl: null, mediaKind: null };

    try {
      if (imageFile) {
        const res = await uploadFile(session.session_id, imageFile, 'image', token);
        imageKey = res.key;
        userMsg.mediaUrl  = URL.createObjectURL(imageFile);
        userMsg.mediaKind = 'image';
        userMsg.content   = text || null;
      } else if (audioFile) {
        const res = await uploadFile(session.session_id, audioFile, 'audio', token);
        audioKey = res.key;
        userMsg.mediaUrl  = URL.createObjectURL(audioFile);
        userMsg.mediaKind = 'audio';
        userMsg.content   = text || null;
      } else {
        userMsg.content = text;
      }
    } catch {
      setBusy(false);
      return;
    }

    setMessages(prev => [...prev, userMsg]);
    socketRef.current?.send({
      text:      text || (imageFile ? 'I just uploaded a visiting card.' : 'Here is a voice note.'),
      image_key: imageKey,
      audio_key: audioKey,
    });
  }

  function startTitleEdit() {
    setTitleValue(session.title);
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 0);
  }

  function commitTitleEdit() {
    const trimmed = titleValue.trim();
    if (trimmed && trimmed !== session.title) onRename(session.session_id, trimmed);
    setEditingTitle(false);
  }

  function handleTitleKey(e) {
    if (e.key === 'Enter')  { e.preventDefault(); commitTitleEdit(); }
    if (e.key === 'Escape') { setEditingTitle(false); }
  }

  function resume(decision) {
    setInterrupt(null);
    setBusy(true);
    socketRef.current?.send({ resume: decision });
  }

  async function handleJoinWaitlist() {
    setWaitlistStatus('sending');
    try {
      await joinWaitlist(waitlistEmail);
      setWaitlistStatus('joined');
    } catch {
      setWaitlistStatus('error');
    }
  }

  function openLimitModal() {
    setWaitlistEmail(userEmail);
    setWaitlistStatus(null);
    setShowLimitModal(true);
  }

  const isEmpty = messages.length === 0 && !streaming && !interrupt;

  return (
    <main className="chat-window">
      <header className="chat-header">
        <span className={`ws-dot ${wsState}`} title={wsState} />
        {editingTitle ? (
          <input
            ref={titleInputRef}
            className="chat-title-input"
            value={titleValue}
            onChange={e => setTitleValue(e.target.value)}
            onBlur={commitTitleEdit}
            onKeyDown={handleTitleKey}
          />
        ) : (
          <h1 className="chat-title" onClick={startTitleEdit} title="Click to rename">
            {session.title}
          </h1>
        )}
      </header>

      {isEmpty ? (
        <div className="empty-state">
          <p>Upload a visiting card to get started</p>
          <div className="empty-actions">
            <label className={`btn btn-primary${limitReached ? ' btn-disabled' : ''}`}
                   onClick={limitReached ? (e) => { e.preventDefault(); openLimitModal(); } : undefined}>
              Upload card
              <input
                type="file" accept="image/*" hidden disabled={limitReached}
                onChange={e => {
                  if (e.target.files[0]) send({ imageFile: e.target.files[0] });
                  e.target.value = '';
                }}
              />
            </label>
            <button className="btn btn-secondary" onClick={() => composerRef.current?.startRecord()}>
              Record voice note
            </button>
          </div>
        </div>
      ) : (
        <div className="thread">
          {messages.map(m => <Message key={m.id} message={m} />)}

          {streaming && (
            <div className="message ai">
              <div className="bubble">{streaming}<span className="cursor" /></div>
            </div>
          )}

          {interrupt && <ConfirmCard ref={confirmCardRef} data={interrupt} onResume={resume} />}

          <div ref={bottomRef} />
        </div>
      )}

      <Composer ref={composerRef} onSend={send} busy={busy || limitReached} />

      {showLimitModal && (
        <div className="limit-overlay" onClick={() => setShowLimitModal(false)}>
          <div className="limit-modal" onClick={e => e.stopPropagation()}>
            <button className="limit-modal-close" onClick={() => setShowLimitModal(false)}>✕</button>
            <h2 className="limit-modal-title">You've used your 2 free scans</h2>
            <p className="limit-modal-sub">CardSync is currently in early access.</p>
            {waitlistStatus === 'joined' ? (
              <p className="limit-modal-success">You're on the list! We'll reach out soon.</p>
            ) : (
              <>
                <input
                  className="limit-modal-input"
                  type="email"
                  value={waitlistEmail}
                  onChange={e => setWaitlistEmail(e.target.value)}
                  placeholder="your@email.com"
                />
                <button
                  className="btn btn-primary limit-modal-btn"
                  disabled={waitlistStatus === 'sending' || !waitlistEmail.trim()}
                  onClick={handleJoinWaitlist}
                >
                  {waitlistStatus === 'sending' ? 'Sending…' : 'Join the waitlist'}
                </button>
                {waitlistStatus === 'error' && (
                  <p className="limit-modal-error">Something went wrong. Try again.</p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
