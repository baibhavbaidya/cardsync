import { useState, forwardRef } from 'react';

const ConfirmCard = forwardRef(function ConfirmCard({ data, onResume }, ref) {
  const isContact = data.action === 'confirm_contact';

  const [contact, setContact]       = useState({ ...(data.contact ?? {}) });
  const [transcript, setTranscript] = useState(data.transcript ?? '');
  const [editing, setEditing]       = useState(false);

  function confirm() {
    if (isContact) {
      onResume(editing
        ? { decision: 'edit', edits: contact }
        : { decision: 'confirm' });
    } else {
      onResume(editing
        ? { decision: 'edit', transcript }
        : { decision: 'confirm' });
    }
  }

  return (
    <div className="confirm-card" ref={ref}>
      <div className="confirm-card-header">
        {isContact ? 'Confirm contact details' : 'Confirm transcript'}
      </div>

      <div className="confirm-card-body">
        {isContact && ['name', 'phone', 'email', 'company'].map(f => (
          <div key={f} className="field-row">
            <label>{f}</label>
            {editing
              ? <input
                  value={contact[f] ?? ''}
                  onChange={e => setContact(c => ({ ...c, [f]: e.target.value }))}
                />
              : <span>{contact[f] || '—'}</span>
            }
          </div>
        ))}

        {!isContact && (editing
          ? <textarea
              className="transcript-edit"
              value={transcript}
              onChange={e => setTranscript(e.target.value)}
              rows={4}
            />
          : transcript
            ? <p className="transcript-preview">{transcript}</p>
            : <p className="transcript-pending">Transcribing…</p>
        )}
      </div>

      <div className="confirm-card-actions">
        <button className="btn btn-secondary" onClick={() => setEditing(e => !e)}>
          {editing ? 'Done' : 'Edit'}
        </button>
        <button className="btn btn-danger" onClick={() => onResume({ decision: 'reject' })}>
          Reject
        </button>
        <button className="btn btn-primary" onClick={confirm}>
          Confirm
        </button>
      </div>
    </div>
  );
});

export default ConfirmCard;
