/**
 * Guest / Photographer page — upload event photos.
 * After upload, facial recognition runs automatically and matched guests
 * receive notifications via their preferred channel.
 */
import { useState } from 'react';
import PhotoDropzone from '../components/PhotoDropzone';
import StatusBadge from '../components/StatusBadge';
import { uploadEventPhotos } from '../services/api';
import { UploadPhotoResult } from '../types';

export default function GuestPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<UploadPhotoResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (files.length === 0) {
      setError('Please select at least one photo.');
      return;
    }

    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const response = await uploadEventPhotos(files, 'guest');
      setResults(response.results);
      setFiles([]);
    } catch (err: any) {
      setError(err.message ?? 'Upload failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  const totalMatches = results?.reduce((sum, r) => sum + r.recognition.matches.length, 0) ?? 0;
  const totalNotified = results?.reduce((sum, r) => sum + r.notifiedGuests.length, 0) ?? 0;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Upload Wedding Photos</h1>
        <p className="page-subtitle">
          Upload photos from the ceremony or banquet. Facial recognition will
          automatically identify guests and send them their photos.
        </p>
      </header>

      <div className="page-layout page-layout--single">
        <section className="card">
          <h2 className="card__title">Upload Photos</h2>

          <PhotoDropzone
            multiple
            label="Drop photos here or click to browse (multiple allowed)"
            onFilesSelected={setFiles}
            disabled={loading}
          />

          {error && <StatusBadge variant="error" message={error} />}
          {loading && (
            <StatusBadge
              variant="loading"
              message="Uploading and running facial recognition… this may take a moment."
            />
          )}

          <button
            type="button"
            className="btn btn--primary btn--full"
            onClick={handleUpload}
            disabled={loading || files.length === 0}
          >
            {loading ? 'Processing…' : `Upload ${files.length > 0 ? `${files.length} Photo${files.length !== 1 ? 's' : ''}` : 'Photos'}`}
          </button>
        </section>

        {/* ── Results panel ── */}
        {results && (
          <section className="card">
            <h2 className="card__title">Recognition Results</h2>

            <div className="stats-row">
              <div className="stat">
                <div className="stat__value">{results.length}</div>
                <div className="stat__label">Photos processed</div>
              </div>
              <div className="stat">
                <div className="stat__value">{totalMatches}</div>
                <div className="stat__label">Faces matched</div>
              </div>
              <div className="stat">
                <div className="stat__value">{totalNotified}</div>
                <div className="stat__label">Guests notified</div>
              </div>
            </div>

            {results.map((r, i) => (
              <div key={r.photo.id ?? i} className="result-item">
                <div className="result-item__header">
                  <strong>{r.photo.originalName}</strong>
                  <span className="badge badge--info">
                    {r.recognition.matches.length} match{r.recognition.matches.length !== 1 ? 'es' : ''}
                  </span>
                </div>

                {r.recognition.matches.length === 0 ? (
                  <p className="result-item__empty">No registered guests detected in this photo.</p>
                ) : (
                  <ul className="match-list">
                    {r.recognition.matches.map((m) => (
                      <li key={m.guestId} className="match-item">
                        <span className="match-item__name">{m.guestName}</span>
                        <span className="match-item__confidence">
                          {m.confidence.toFixed(1)}% confidence
                        </span>
                        <span
                          className={`badge ${r.notifiedGuests.includes(m.guestName) ? 'badge--success' : 'badge--warning'}`}
                        >
                          {r.notifiedGuests.includes(m.guestName) ? 'Notified' : 'Notification failed'}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
