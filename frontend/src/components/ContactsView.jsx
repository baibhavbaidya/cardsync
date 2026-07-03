import { Fragment, useState, useEffect } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { getContacts, exportContacts } from '../api';

const PER_PAGE = 10;

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function ContactsView() {
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
      .catch(()   => { if (!cancelled) setLoading(false); });
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

  function handleSearch(e) { setSearch(e.target.value); setPage(1); }

  function toggle(id) { setExpanded(prev => prev === id ? null : id); }

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

  return (
    <div className="contacts-view">
      <div className="cv-header">
        <h1 className="cv-title">My Contacts</h1>
        <button className="btn btn-secondary" onClick={handleExport}>Export CSV</button>
      </div>

      <div className="cv-search-bar">
        <input
          className="cv-search-input"
          type="search"
          placeholder="Search by name, company, or email…"
          value={search}
          onChange={handleSearch}
        />
      </div>

      {loading ? (
        <div className="cv-status">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="cv-status">
          {search
            ? 'No contacts match your search.'
            : 'No contacts yet. Upload a visiting card to get started.'}
        </div>
      ) : (
        <>
          <div className="cv-table-wrap">
            <table className="cv-table">
              <colgroup>
                <col className="col-cv-name" />
                <col className="col-cv-company" />
                <col className="col-cv-phone" />
                <col className="col-cv-email" />
                <col className="col-cv-created" />
                <col className="col-cv-chevron" />
              </colgroup>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Company</th>
                  <th>Phone</th>
                  <th>Email</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {pageItems.map(c => (
                  <Fragment key={c.id}>
                    <tr
                      className={`cv-row${expanded === c.id ? ' cv-row--open' : ''}`}
                      onClick={() => toggle(c.id)}
                    >
                      <td className="cv-cell cv-name">{c.name || '—'}</td>
                      <td className="cv-cell cv-muted">{c.company || '—'}</td>
                      <td className="cv-cell cv-muted">{c.phone || '—'}</td>
                      <td className="cv-cell cv-muted">{c.email || '—'}</td>
                      <td className="cv-cell cv-muted">{fmtDate(c.created_at)}</td>
                      <td className="cv-chevron-cell">{expanded === c.id ? '▲' : '▼'}</td>
                    </tr>

                    {expanded === c.id && (
                      <tr className="cv-detail-row">
                        <td colSpan={6}>
                          <div className="cv-detail">
                            {c.website && (
                              <div className="cv-detail-field">
                                <span className="cv-field-label">Website</span>
                                <a href={c.website} target="_blank" rel="noreferrer" className="cv-field-link">{c.website}</a>
                              </div>
                            )}
                            {c.linkedin && (
                              <div className="cv-detail-field">
                                <span className="cv-field-label">LinkedIn</span>
                                <a href={c.linkedin} target="_blank" rel="noreferrer" className="cv-field-link">{c.linkedin}</a>
                              </div>
                            )}
                            {c.audio_url && (
                              <div className="cv-detail-field">
                                <span className="cv-field-label">Audio</span>
                                <audio controls src={c.audio_url} className="cv-audio" />
                              </div>
                            )}
                            {c.transcript && (
                              <div className="cv-detail-field cv-detail-field--block">
                                <span className="cv-field-label">Transcript</span>
                                <p className="cv-transcript-text">{c.transcript}</p>
                              </div>
                            )}
                            {!c.website && !c.linkedin && !c.audio_url && !c.transcript && (
                              <span className="cv-detail-empty">No additional details.</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <div className="cv-footer">
            <button
              className="btn btn-secondary"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={safePage <= 1}
            >← Prev</button>
            <span className="cv-page-info">Page {safePage} of {totalPages}</span>
            <button
              className="btn btn-secondary"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={safePage >= totalPages}
            >Next →</button>
          </div>
        </>
      )}
    </div>
  );
}
