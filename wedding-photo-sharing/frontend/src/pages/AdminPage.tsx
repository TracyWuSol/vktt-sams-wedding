/**
 * Admin page — register wedding guests with reference photos.
 * Reference photos are indexed in AWS Rekognition for later face matching.
 */
import { useState, useEffect, FormEvent } from 'react';
import PhotoDropzone from '../components/PhotoDropzone';
import GuestCard from '../components/GuestCard';
import StatusBadge from '../components/StatusBadge';
import {
  registerGuest,
  fetchGuests,
  resetRegistry,
  updateGuestContact,
  deleteGuest,
} from '../services/api';
import { Guest, NotificationChannel } from '../types';

const CHANNELS: NotificationChannel[] = ['email', 'line', 'sms'];

interface FormState {
  name: string;
  email: string;
  phone: string;
  preferredChannel: NotificationChannel;
}

const EMPTY_FORM: FormState = {
  name: '',
  email: '',
  phone: '',
  preferredChannel: 'email',
};

export default function AdminPage() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [photo, setPhoto] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [guests, setGuests] = useState<Guest[]>([]);
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [fetchingGuests, setFetchingGuests] = useState(true);
  const [submitStatus, setSubmitStatus] = useState<
    { type: 'success' | 'error'; message: string } | null
  >(null);

  useEffect(() => {
    loadGuests();
  }, []);

  async function handleReset() {
    if (!window.confirm('This will delete ALL registered guests and clear the face index. Are you sure?')) return;
    setResetting(true);
    setSubmitStatus(null);
    try {
      await resetRegistry();
      setGuests([]);
      setSubmitStatus({ type: 'success', message: 'Registry cleared. Please re-register all guests.' });
    } catch (err: any) {
      setSubmitStatus({ type: 'error', message: `Reset failed: ${err.message}` });
    } finally {
      setResetting(false);
    }
  }

  async function handleUpdateGuest(id: string, patch: { email: string; phone: string }) {
    const updated = await updateGuestContact(id, patch);
    setGuests((prev) => prev.map((g) => (g.id === id ? updated : g)));
  }

  async function handleDeleteGuest(id: string) {
    await deleteGuest(id);
    setGuests((prev) => prev.filter((g) => g.id !== id));
  }

  async function loadGuests() {
    setFetchingGuests(true);
    try {
      const list = await fetchGuests();
      setGuests(list);
    } catch (err: any) {
      console.error('Failed to load guests:', err);
    } finally {
      setFetchingGuests(false);
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!photo) {
      setSubmitStatus({ type: 'error', message: 'Please select a reference photo.' });
      return;
    }

    setLoading(true);
    setSubmitStatus(null);

    try {
      const guest = await registerGuest({ ...form, photo });
      setGuests((prev) => [guest, ...prev]);
      setForm(EMPTY_FORM);
      setPhoto(null);
      setConsent(false);
      setSubmitStatus({
        type: 'success',
        message: `${guest.name} registered successfully${guest.faceId ? ' and face indexed.' : ' (face indexing failed — check reference photo quality).'}`,
      });
    } catch (err: any) {
      setSubmitStatus({ type: 'error', message: err.message ?? 'Registration failed.' });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Admin — Guest Registry</h1>
        <p className="page-subtitle">
          Register guests with a clear face photo. Faces are indexed in AWS Rekognition
          and matched against photos uploaded during the ceremony.
        </p>
      </header>

      <div className="page-layout">
        {/* ── Registration form ── */}
        <section className="card">
          <h2 className="card__title">Register New Guest</h2>
          <form onSubmit={handleSubmit} noValidate>
            <div className="form-group">
              <label htmlFor="name">Full name *</label>
              <input
                id="name"
                name="name"
                type="text"
                value={form.name}
                onChange={handleInput}
                placeholder="Jane Smith"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="email">Email *</label>
              <input
                id="email"
                name="email"
                type="email"
                value={form.email}
                onChange={handleInput}
                placeholder="jane@example.com"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="phone">Phone (with country code) *</label>
              <input
                id="phone"
                name="phone"
                type="tel"
                value={form.phone}
                onChange={handleInput}
                placeholder="+65 9012 3456"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="preferredChannel">Preferred notification channel *</label>
              <select
                id="preferredChannel"
                name="preferredChannel"
                value={form.preferredChannel}
                onChange={handleInput}
              >
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>
                    {c.charAt(0).toUpperCase() + c.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Reference photo (clear face, single person) *</label>
              <PhotoDropzone
                multiple={false}
                label="Drop or click to select reference photo"
                onFilesSelected={(files) => setPhoto(files[0] ?? null)}
                disabled={loading}
              />
            </div>

            <div className="consent-box">
              <label className="consent-label">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  disabled={loading}
                />
                <span>
                  I consent to having a face vector extracted from this reference
                  photo and stored in AWS Rekognition for the sole purpose of
                  matching me in wedding photos. I understand the stored vector
                  can be deleted at any time by removing my guest record, which
                  also revokes future matching.
                </span>
              </label>
            </div>

            {submitStatus && (
              <StatusBadge
                variant={submitStatus.type === 'success' ? 'success' : 'error'}
                message={submitStatus.message}
              />
            )}

            <button
              type="submit"
              className="btn btn--primary"
              disabled={loading || !consent}
              title={!consent ? 'Consent is required before registering' : undefined}
            >
              {loading ? 'Registering…' : 'Register Guest'}
            </button>
          </form>
        </section>

        {/* ── Guest list ── */}
        <section className="card">
          <div className="card__title-row">
            <h2 className="card__title">Registered Guests ({guests.length})</h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={loadGuests}
                disabled={fetchingGuests}
              >
                {fetchingGuests ? 'Loading…' : 'Refresh'}
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                style={{ color: '#ef4444' }}
                onClick={handleReset}
                disabled={resetting}
              >
                {resetting ? 'Resetting…' : 'Reset All'}
              </button>
            </div>
          </div>

          {fetchingGuests ? (
            <StatusBadge variant="loading" message="Loading guests…" />
          ) : guests.length === 0 ? (
            <p className="empty-state">No guests registered yet.</p>
          ) : (
            <div className="guest-list">
              {guests.map((g) => (
                <GuestCard
                  key={g.id}
                  guest={g}
                  onSave={handleUpdateGuest}
                  onDelete={handleDeleteGuest}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
