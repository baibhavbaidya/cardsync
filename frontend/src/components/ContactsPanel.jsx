import { useState, useEffect } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { getContacts, exportContacts } from '../api';

const PER_PAGE = 10;

export default function ContactsPanel() {
  const { getToken } = useAuth();
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState('');
  const [page, setPage]         = useState(1);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getToken()
      .then(token => getContacts(token))
      .then(data  => { if (!cancelled) { setContacts(data); setLoading(false); } })
      .catch(()   => { if (!cancelled)   setLoading(false); });
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = contacts.filter(c => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      (c.name    || '').toLowerCase().includes(q) ||
      (c.company || '').toLowerCase().includes(q) ||
      (c.email   || '').toLowerCase().includes(q)
    );
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
  const safePage   = Math.min(page, totalPages);
  const pageItems  = filtered.slice((safePage - 1) * PER_PAGE, safePage * PER_PAGE);

  async function handleExport() {
    try {
      const token = await getToken();
      const blob  = await exportContacts(token);
      const url   = URL.createObjectURL(blob);
      const a     = document.createElement('a');
      a.href = url; a.download = 'contacts.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
    }
  }

  function handleSearch(e) {
    setSearch(e.target.value);
    setPage(1);
  }

  if (loading) return <div className="contacts-empty">Loading…</div>;

  return (
    <div className="contacts-panel">
      <div className="contacts-toolbar">
        <input
          className="contacts-search"
          type="search"
          placeholder="Search name, company, email…"
          value={search}
          onChange={handleSearch}
        />
        <button className="btn-export" onClick={handleExport} title="Export as CSV">
          ↓ CSV
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="contacts-empty">
          {search ? 'No results.' : 'No contacts yet.'}
        </div>
      ) : (
        <>
          <div className="contacts-table-head">
            <span>Name</span>
            <span>Company</span>
            <span>Phone</span>
            <span>Email</span>
            <span />
          </div>

          <div className="contacts-list">
            {pageItems.map(c => (
              <div
                key={c.id}
                className={`contact-row${expanded === c.id ? ' expanded' : ''}`}
              >
                <div
                  className="contact-row-main"
                  onClick={() => setExpanded(prev => prev === c.id ? null : c.id)}
                >
                  <span className="contact-cell contact-name-cell" title={c.name}>{c.name || '—'}</span>
                  <span className="contact-cell contact-muted" title={c.company}>{c.company || '—'}</span>
                  <span className="contact-cell contact-muted">{c.phone || '—'}</span>
                  <span className="contact-cell contact-muted" title={c.email}>{c.email || '—'}</span>
                  <span className="contact-chevron">{expanded === c.id ? '▲' : '▼'}</span>
                </div>

                {expanded === c.id && (
                  <div className="contact-detail">
                    {c.website && (
                      <div className="cd-row">
                        <span className="cd-label">Website</span>
                        <a href={c.website} target="_blank" rel="noreferrer" className="cd-val cd-link">{c.website}</a>
                      </div>
                    )}
                    {c.linkedin && (
                      <div className="cd-row">
                        <span className="cd-label">LinkedIn</span>
                        <a href={c.linkedin} target="_blank" rel="noreferrer" className="cd-val cd-link">{c.linkedin}</a>
                      </div>
                    )}
                    {c.audio_url && (
                      <div className="cd-row">
                        <span className="cd-label">Audio</span>
                        <audio controls src={c.audio_url} className="contact-audio" />
                      </div>
                    )}
                    {c.transcript && (
                      <div className="cd-row cd-row--block">
                        <span className="cd-label">Transcript</span>
                        <p className="cd-transcript">{c.transcript}</p>
                      </div>
                    )}
                    {!c.website && !c.linkedin && !c.audio_url && !c.transcript && (
                      <p className="cd-empty">No additional details.</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="contacts-pagination">
              <button
                className="page-btn"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={safePage <= 1}
              >← Prev</button>
              <span className="page-info">{safePage} / {totalPages}</span>
              <button
                className="page-btn"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
              >Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
