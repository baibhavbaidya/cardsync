import { useState, useRef, forwardRef, useImperativeHandle } from 'react';

const Composer = forwardRef(function Composer({ onSend, busy }, ref) {
  const [text, setText]         = useState('');
  const [recording, setRec]     = useState(false);
  const imageInputRef           = useRef(null);
  const textareaRef             = useRef(null);
  const mediaRecRef             = useRef(null);
  const chunksRef               = useRef([]);

  useImperativeHandle(ref, () => ({
    triggerImage:  () => imageInputRef.current?.click(),
    startRecord:   () => toggleRecord(),
  }));

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  async function toggleRecord() {
    if (recording) { mediaRecRef.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = e => chunksRef.current.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/ogg; codecs=opus' });
        setRec(false);
        onSend({ audioFile: new File([blob], 'voice-note.ogg', { type: 'audio/ogg' }) });
      };
      mr.start();
      mediaRecRef.current = mr;
      setRec(true);
    } catch { /* mic permission denied */ }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  }

  function submit() {
    if (busy || !text.trim()) return;
    onSend({ text: text.trim() });
    setText('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }

  return (
    <div className="composer">
      <button
        className="composer-btn"
        title="Upload card image"
        disabled={busy}
        onClick={() => imageInputRef.current?.click()}
      >📎</button>
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={e => {
          if (e.target.files[0]) onSend({ imageFile: e.target.files[0] });
          e.target.value = '';
        }}
      />

      <button
        className={`composer-btn${recording ? ' recording' : ''}`}
        title={recording ? 'Stop recording' : 'Record voice note'}
        disabled={busy && !recording}
        onClick={toggleRecord}
      >{recording ? '⏹' : '🎙'}</button>

      <textarea
        ref={textareaRef}
        className="composer-input"
        value={text}
        placeholder="Type a message…"
        disabled={busy}
        rows={1}
        onInput={autoResize}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKey}
      />

      <button
        className="composer-btn send"
        disabled={!recording && (busy || !text.trim())}
        onClick={recording ? toggleRecord : submit}
        title={recording ? 'Stop recording and send' : 'Send'}
      >↑</button>
    </div>
  );
});

export default Composer;
