/**
 * Health / status route.
 * GET /api/status  – returns counts of guests, photos, notifications
 */
import { Router, Request, Response } from 'express';
import { guestStore } from '../store/guestStore';

const router = Router();

router.get('/', (_req: Request, res: Response): void => {
  const guests = guestStore.getAllGuests();
  const photos = guestStore.getAllPhotos();
  const notifications = guestStore.getAllNotifications();
  const recognitions = guestStore.getAllRecognitionResults();

  res.json({
    status: 'ok',
    stats: {
      registeredGuests: guests.length,
      guestsWithFaceIndex: guests.filter((g) => g.faceId).length,
      totalPhotosUploaded: photos.length,
      eventPhotos: photos.filter((p) => p.uploadType === 'event').length,
      referencePhotos: photos.filter((p) => p.uploadType === 'reference').length,
      recognitionResults: recognitions.length,
      totalMatchesFound: recognitions.reduce((sum, r) => sum + r.matches.length, 0),
      notificationsSent: notifications.filter((n) => n.status === 'sent').length,
      notificationsFailed: notifications.filter((n) => n.status === 'failed').length,
    },
  });
});

export default router;
