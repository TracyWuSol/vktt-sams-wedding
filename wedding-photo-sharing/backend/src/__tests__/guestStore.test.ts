import { GuestStore } from '../store/guestStore';
import { Guest, NotificationRecord, RecognitionResult, UploadedPhoto } from '../types';

// Use a fresh store instance per test to avoid cross-test contamination
function makeStore() {
  // Re-import a fresh store by instantiating the class directly
  const { GuestStore: GS } = jest.requireActual('../store/guestStore') as {
    GuestStore: new () => GuestStore;
  };
  return new GS();
}

describe('GuestStore', () => {
  describe('guests', () => {
    it('adds and retrieves a guest by id', () => {
      const store = makeStore();
      const guest: Guest = {
        id: 'g1',
        name: 'Alice',
        email: 'alice@example.com',
        phone: '+1234567890',
        preferredChannel: 'email',
        createdAt: new Date().toISOString(),
      };
      store.addGuest(guest);
      expect(store.getGuest('g1')).toEqual(guest);
    });

    it('returns undefined for unknown guest', () => {
      const store = makeStore();
      expect(store.getGuest('none')).toBeUndefined();
    });

    it('lists all guests', () => {
      const store = makeStore();
      const g1: Guest = { id: 'g1', name: 'Alice', email: 'a@a.com', phone: '+1', preferredChannel: 'email', createdAt: '' };
      const g2: Guest = { id: 'g2', name: 'Bob', email: 'b@b.com', phone: '+2', preferredChannel: 'sms', createdAt: '' };
      store.addGuest(g1);
      store.addGuest(g2);
      expect(store.getAllGuests()).toHaveLength(2);
    });

    it('updates a guest', () => {
      const store = makeStore();
      const guest: Guest = { id: 'g1', name: 'Alice', email: 'a@a.com', phone: '+1', preferredChannel: 'email', createdAt: '' };
      store.addGuest(guest);
      const updated = store.updateGuest('g1', { faceId: 'face-abc' });
      expect(updated?.faceId).toBe('face-abc');
      expect(store.getGuest('g1')?.faceId).toBe('face-abc');
    });

    it('returns undefined when updating non-existent guest', () => {
      const store = makeStore();
      expect(store.updateGuest('nope', { name: 'X' })).toBeUndefined();
    });

    it('finds guest by faceId', () => {
      const store = makeStore();
      const guest: Guest = { id: 'g1', name: 'Alice', email: 'a@a.com', phone: '+1', preferredChannel: 'email', faceId: 'face-123', createdAt: '' };
      store.addGuest(guest);
      expect(store.findByFaceId('face-123')?.id).toBe('g1');
      expect(store.findByFaceId('face-999')).toBeUndefined();
    });
  });

  describe('photos', () => {
    it('adds and retrieves a photo', () => {
      const store = makeStore();
      const photo: UploadedPhoto = {
        id: 'p1', s3Key: 'events/p1.jpg', s3Url: 'https://...', uploadedBy: 'guest',
        uploadType: 'event', uploadedAt: '', originalName: 'photo.jpg', mimeType: 'image/jpeg', sizeBytes: 1024,
      };
      store.addPhoto(photo);
      expect(store.getPhoto('p1')).toEqual(photo);
    });
  });

  describe('notifications', () => {
    it('stores and retrieves notifications per guest', () => {
      const store = makeStore();
      const n1: NotificationRecord = { id: 'n1', guestId: 'g1', channel: 'email', photoS3Key: 'events/p.jpg', status: 'sent', sentAt: '' };
      const n2: NotificationRecord = { id: 'n2', guestId: 'g2', channel: 'sms', photoS3Key: 'events/p.jpg', status: 'failed', sentAt: '' };
      store.addNotification(n1);
      store.addNotification(n2);
      expect(store.getNotificationsForGuest('g1')).toHaveLength(1);
      expect(store.getNotificationsForGuest('g2')[0].status).toBe('failed');
    });
  });

  describe('recognition results', () => {
    it('stores and retrieves results', () => {
      const store = makeStore();
      const result: RecognitionResult = {
        photoId: 'p1', s3Key: 'events/p1.jpg',
        matches: [{ guestId: 'g1', guestName: 'Alice', confidence: 95 }],
        processedAt: '',
      };
      store.addRecognitionResult(result);
      expect(store.getRecognitionResult('p1')?.matches).toHaveLength(1);
    });
  });
});
