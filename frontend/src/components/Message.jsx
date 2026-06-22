const TOOL_LABELS = {
  extract_card_details:  'Extracting card details',
  check_duplicate:       'Checking for duplicates',
  log_contact_to_sheet:  'Logging contact to sheet',
  send_whatsapp_alert:   'Sending WhatsApp alert',
  store_voice_note:      'Storing voice note',
  enrich_company:        'Enriching company data',
};

export default function Message({ message }) {
  if (message.type === 'tool') {
    const done = message.status === 'done';
    return (
      <div className={`tool-step${done ? ' done' : ''}`}>
        <span className={done ? undefined : 'spin'}>
          {done ? '✓' : '↻'}
        </span>
        <span>{TOOL_LABELS[message.name] ?? message.name.replace(/_/g, ' ')}</span>
      </div>
    );
  }

  return (
    <div className={`message ${message.type}`}>
      <div className="bubble">
        {message.mediaKind === 'image' && message.mediaUrl && (
          <img src={message.mediaUrl} alt="visiting card" className="msg-image" />
        )}
        {message.mediaKind === 'audio' && message.mediaUrl && (
          <audio controls src={message.mediaUrl} className="msg-audio" />
        )}
        {message.content && <p>{message.content}</p>}
      </div>
    </div>
  );
}
