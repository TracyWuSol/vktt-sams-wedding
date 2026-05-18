/**
 * Guest store with JSON-file persistence.
 * Guests (including their Rekognition faceIds) survive server restarts and
 * hot-reloads, so uploaded event photos can still be matched after a reload.
 *
 * Only guests are persisted — photos, recognition results, and notifications
 * are session-only and reset on restart (they can be re-derived from S3/Rekognition).
 */
import fs from 'fs';
import path from 'path';
import { Guest, UploadedPhoto, RecognitionResult, NotificationRecord } from '../types';

const DATA_DIR  = path.resolve(__dirname, '../../data');
const GUESTS_FILE = path.join(DATA_DIR, 'guests.json');

function ensureDataDir(): void {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function loadGuests(): Map<string, Guest> {
  ensureDataDir();
  try {
    if (!fs.existsSync(GUESTS_FILE)) return new Map();
    const raw = fs.readFileSync(GUESTS_FILE, 'utf-8');
    const arr = JSON.parse(raw) as Guest[];
    return new Map(arr.map((g) => [g.id, g]));
  } catch {
    console.warn('[GuestStore] Could not load guests.json — starting fresh');
    return new Map();
  }
}

function saveGuests(guests: Map<string, Guest>): void {
  ensureDataDir();
  try {
    fs.writeFileSync(GUESTS_FILE, JSON.stringify(Array.from(guests.values()), null, 2));
  } catch (err) {
    console.error('[GuestStore] Failed to save guests.json:', err);
  }
}

export class GuestStore {
  private guests = loadGuests(); // restored from disk on construction
  private photos = new Map<string, UploadedPhoto>();
  private recognitionResults = new Map<string, RecognitionResult>();
  private notifications: NotificationRecord[] = [];

  // ---------- Guests ----------

  addGuest(guest: Guest): void {
    this.guests.set(guest.id, guest);
    saveGuests(this.guests);
  }

  getGuest(id: string): Guest | undefined {
    return this.guests.get(id);
  }

  getAllGuests(): Guest[] {
    return Array.from(this.guests.values());
  }

  updateGuest(id: string, patch: Partial<Guest>): Guest | undefined {
    const existing = this.guests.get(id);
    if (!existing) return undefined;
    const updated = { ...existing, ...patch };
    this.guests.set(id, updated);
    saveGuests(this.guests);
    return updated;
  }

  removeGuest(id: string): Guest | undefined {
    const existing = this.guests.get(id);
    if (!existing) return undefined;
    this.guests.delete(id);
    saveGuests(this.guests);
    return existing;
  }

  // Find the guest whose faceId matches the Rekognition face ID
  findByFaceId(faceId: string): Guest | undefined {
    return Array.from(this.guests.values()).find((g) => g.faceId === faceId);
  }

  // ---------- Reset ----------

  /** Wipe all in-memory data. Call AFTER clearing guests.json on disk. */
  clearAll(): void {
    this.guests.clear();
    this.photos.clear();
    this.recognitionResults.clear();
    this.notifications = [];
  }

  // ---------- Photos (session-only) ----------

  addPhoto(photo: UploadedPhoto): void {
    this.photos.set(photo.id, photo);
  }

  getPhoto(id: string): UploadedPhoto | undefined {
    return this.photos.get(id);
  }

  getAllPhotos(): UploadedPhoto[] {
    return Array.from(this.photos.values());
  }

  // ---------- Recognition (session-only) ----------

  addRecognitionResult(result: RecognitionResult): void {
    this.recognitionResults.set(result.photoId, result);
  }

  getRecognitionResult(photoId: string): RecognitionResult | undefined {
    return this.recognitionResults.get(photoId);
  }

  getAllRecognitionResults(): RecognitionResult[] {
    return Array.from(this.recognitionResults.values());
  }

  // ---------- Notifications (session-only) ----------

  addNotification(record: NotificationRecord): void {
    this.notifications.push(record);
  }

  getNotificationsForGuest(guestId: string): NotificationRecord[] {
    return this.notifications.filter((n) => n.guestId === guestId);
  }

  getAllNotifications(): NotificationRecord[] {
    return [...this.notifications];
  }
}

// Singleton shared across all route handlers
export const guestStore = new GuestStore();
