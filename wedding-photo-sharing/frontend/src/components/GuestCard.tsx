import { useState } from 'react';
import { Guest } from '../types';

const CHANNEL_ICON: Record<string, string> = {
  email: '✉️',
  line: '💚',
  sms: '📱',
};

interface Props {
  guest: Guest;
  onSave?: (id: string, patch: { email: string; phone: string }) => Promise<void>;
  onDelete?: (id: string) => Promise<void>;
}

export default function GuestCard({ guest, onSave, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [email, setEmail] = useState(guest.email);
  const [phone, setPhone] = useState(guest.phone);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function beginEdit() {
    setEmail(guest.email);
    setPhone(guest.phone);
    setError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setError(null);
  }

  async function save() {
    if (!onSave) return;
    const trimmedEmail = email.trim();
    const trimmedPhone = phone.trim();
    if (!trimmedEmail.includes('@')) {
      setError('Email looks invalid');
      return;
    }
    if (!trimmedPhone) {
      setError('Phone cannot be empty');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(guest.id, { email: trimmedEmail, phone: trimmedPhone });
      setEditing(false);
    } catch (err: any) {
      setError(err.message ?? 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!onDelete) return;
    if (!window.confirm(`Delete ${guest.name}? This also removes their face from the index.`)) return;
    setDeleting(true);
    try {
      await onDelete(guest.id);
    } catch (err: any) {
      setError(err.message ?? 'Failed to delete');
      setDeleting(false);
    }
  }

  return (
    <div className="guest-card">
      <div className="guest-card__avatar">
        {guest.referencePhotoUrl ? (
          <img
            src={guest.referencePhotoUrl}
            alt={guest.name}
            loading="lazy"
          />
        ) : (
          guest.name.charAt(0).toUpperCase()
        )}
      </div>
      <div className="guest-card__info">
        <div className="guest-card__name">{guest.name}</div>
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              disabled={saving}
              style={{ fontSize: 12, padding: '4px 6px' }}
            />
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Phone"
              disabled={saving}
              style={{ fontSize: 12, padding: '4px 6px' }}
            />
            {error && <div style={{ fontSize: 11, color: '#ef4444' }}>{error}</div>}
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={save}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={cancelEdit}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="guest-card__contact">{guest.email}</div>
            <div className="guest-card__contact">{guest.phone}</div>
            {error && <div style={{ fontSize: 11, color: '#ef4444' }}>{error}</div>}
          </>
        )}
      </div>
      <div className="guest-card__meta">
        <span
          className={`badge badge--${guest.preferredChannel}`}
          title={`Preferred: ${guest.preferredChannel}`}
        >
          {CHANNEL_ICON[guest.preferredChannel]} {guest.preferredChannel}
        </span>
        <span className={`badge ${guest.faceId ? 'badge--success' : 'badge--warning'}`}>
          {guest.faceId ? '✓ Face indexed' : '⚠ No face'}
        </span>
        {!editing && (onSave || onDelete) && (
          <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
            {onSave && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={beginEdit}
                disabled={deleting}
              >
                Edit
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                style={{ color: '#ef4444' }}
                onClick={remove}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
