import {
  Guest,
  NotificationChannel,
  UploadPhotosResponse,
  StatusStats,
} from '../types';

const BASE = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ─── Guests ──────────────────────────────────────────────────────────────────

export interface RegisterGuestPayload {
  name: string;
  email: string;
  phone: string;
  preferredChannel: NotificationChannel;
  photo: File; // reference photo for facial recognition
}

export async function registerGuest(payload: RegisterGuestPayload): Promise<Guest> {
  const form = new FormData();
  form.append('name', payload.name);
  form.append('email', payload.email);
  form.append('phone', payload.phone);
  form.append('preferredChannel', payload.preferredChannel);
  form.append('photo', payload.photo);

  const res = await fetch(`${BASE}/guests`, { method: 'POST', body: form });
  const data = await handleResponse<{ guest: Guest }>(res);
  return data.guest;
}

export async function fetchGuests(): Promise<Guest[]> {
  const res = await fetch(`${BASE}/guests`);
  const data = await handleResponse<{ guests: Guest[] }>(res);
  return data.guests;
}

export async function updateGuestContact(
  id: string,
  patch: { email?: string; phone?: string }
): Promise<Guest> {
  const res = await fetch(`${BASE}/guests/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  const data = await handleResponse<{ guest: Guest }>(res);
  return data.guest;
}

export async function deleteGuest(id: string): Promise<void> {
  const res = await fetch(`${BASE}/guests/${id}`, { method: 'DELETE' });
  await handleResponse<unknown>(res);
}

// ─── Photos ───────────────────────────────────────────────────────────────────

export type UploaderRole = 'guest' | 'photographer' | 'admin';

export async function uploadEventPhotos(
  files: File[],
  uploadedBy: UploaderRole
): Promise<UploadPhotosResponse> {
  const form = new FormData();
  form.append('uploadedBy', uploadedBy);
  files.forEach((f) => form.append('photos', f));

  const res = await fetch(`${BASE}/upload-photos`, { method: 'POST', body: form });
  return handleResponse<UploadPhotosResponse>(res);
}

// ─── Admin ────────────────────────────────────────────────────────────────────

/** Purge Rekognition collection and clear the guest store. */
export async function resetRegistry(): Promise<void> {
  const res = await fetch(`${BASE}/admin/reset`, { method: 'POST' });
  await handleResponse<unknown>(res);
}

// ─── Status ───────────────────────────────────────────────────────────────────

export async function fetchStatus(): Promise<StatusStats> {
  const res = await fetch(`${BASE}/status`);
  const data = await handleResponse<{ status: string; stats: StatusStats }>(res);
  return data.stats;
}
