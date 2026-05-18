/**
 * Guest registry routes (admin-facing).
 *
 * POST /api/guests          – register a guest (with reference photo)
 * GET  /api/guests          – list all guests
 * GET  /api/guests/:id      – get a single guest
 * GET  /api/guests/:id/notifications – notification history for a guest
 */
import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { uploadSingle } from '../middleware/upload';
import { validateGuestCreate, validateFilesPresent } from '../middleware/validation';
import { uploadToS3, buildS3Url, uploadMetadataToS3, getPresignedUrl } from '../services/s3Service';
import { indexGuestFace, deleteFace } from '../services/rekognitionService';
import { toRekognitionCompatible } from '../services/imageUtils';
import { publishPhotoUploaded } from '../services/solaceService';
import { guestStore } from '../store/guestStore';
import { Guest, GuestCreateInput } from '../types';

const router = Router();

// Attach a presigned URL for the reference photo so the frontend can render
// it as an avatar. URL expires (default 24h) — generated fresh on every read.
async function withReferenceUrl(guest: Guest): Promise<Guest & { referencePhotoUrl?: string }> {
  if (!guest.referencePhotoKey) return guest;
  try {
    const referencePhotoUrl = await getPresignedUrl(guest.referencePhotoKey);
    return { ...guest, referencePhotoUrl };
  } catch (err) {
    console.error(`[Guests] Could not presign reference photo for ${guest.id}:`, err);
    return guest;
  }
}

// Register a guest and upload their reference photo for facial recognition
router.post(
  '/',
  uploadSingle,
  validateFilesPresent,
  validateGuestCreate,
  async (req: Request, res: Response): Promise<void> => {
    const { name, email, phone, preferredChannel } = req.body as GuestCreateInput;
    const file = req.file!;

    const guestId = uuidv4();

    try {
      // Convert to JPEG if needed — Rekognition only accepts JPEG and PNG
      const { buffer, mimeType } = await toRekognitionCompatible(file.buffer, file.mimetype);

      // 1. Upload reference photo to S3 under the "references/" prefix
      const s3Key = await uploadToS3(
        buffer,
        mimeType === 'image/jpeg' ? `${guestId}.jpg` : file.originalname,
        mimeType,
        'references',
        guestId
      );

      // 2. Index the face in AWS Rekognition; store guestId as externalImageId
      let faceId: string | undefined;
      try {
        faceId = await indexGuestFace(s3Key, guestId);
      } catch (rekErr) {
        console.error('[Rekognition] Face indexing failed:', rekErr);
        // Still create the guest; recognition will just never match them
      }

      // 3. Persist guest record
      const guest: Guest = {
        id: guestId,
        name,
        email,
        phone,
        preferredChannel,
        faceId,
        referencePhotoKey: s3Key,
        createdAt: new Date().toISOString(),
      };
      guestStore.addGuest(guest);

      // 4. Publish S3 upload event to Solace so downstream systems can react
      publishPhotoUploaded({
        photoId: guestId,
        s3Key,
        uploadType: 'reference',
        uploadedBy: 'admin',
        guestId,
        timestamp: guest.createdAt,
      });

      // 5. Upload reference photo metadata to S3 for the Solace Micro-integration
      const metadataKey = `metadata/references/${guestId}.json`;
      await uploadMetadataToS3(
        {
          photoId: guestId,
          s3Key,
          s3Url: buildS3Url(s3Key),
          originalName: file.originalname,
          mimeType,
          sizeBytes: buffer.length,
          uploadedBy: 'admin',
          uploadType: 'reference',
          uploadedAt: guest.createdAt,
          guestId,
          guestName: name,
        },
        metadataKey
      ).catch((err: any) => console.error(`[Metadata] Failed to upload ${metadataKey}:`, err));

      res.status(201).json({
        guest: await withReferenceUrl(guest),
        s3Url: buildS3Url(s3Key),
        faceIndexed: !!faceId,
      });
    } catch (err: any) {
      console.error('[POST /api/guests] Error:', err);
      res.status(500).json({ error: 'Failed to register guest', details: err.message });
    }
  }
);

// List all registered guests
router.get('/', async (_req: Request, res: Response): Promise<void> => {
  const guests = await Promise.all(guestStore.getAllGuests().map(withReferenceUrl));
  res.json({ guests });
});

// Get a single guest by ID
router.get('/:id', async (req: Request, res: Response): Promise<void> => {
  const guest = guestStore.getGuest(req.params.id);
  if (!guest) {
    res.status(404).json({ error: 'Guest not found' });
    return;
  }
  res.json({ guest: await withReferenceUrl(guest) });
});

// Update editable fields (email + phone) on a guest
router.patch('/:id', async (req: Request, res: Response): Promise<void> => {
  const { email, phone } = (req.body ?? {}) as { email?: unknown; phone?: unknown };
  const patch: { email?: string; phone?: string } = {};

  if (email !== undefined) {
    if (typeof email !== 'string' || !email.includes('@')) {
      res.status(400).json({ error: 'Invalid email' });
      return;
    }
    patch.email = email.trim();
  }
  if (phone !== undefined) {
    if (typeof phone !== 'string' || phone.trim().length === 0) {
      res.status(400).json({ error: 'Invalid phone' });
      return;
    }
    patch.phone = phone.trim();
  }

  if (Object.keys(patch).length === 0) {
    res.status(400).json({ error: 'No editable fields supplied (email, phone)' });
    return;
  }

  const updated = guestStore.updateGuest(req.params.id, patch);
  if (!updated) {
    res.status(404).json({ error: 'Guest not found' });
    return;
  }
  res.json({ guest: await withReferenceUrl(updated) });
});

// Delete a single guest (and their face from the Rekognition collection)
router.delete('/:id', async (req: Request, res: Response): Promise<void> => {
  const guest = guestStore.getGuest(req.params.id);
  if (!guest) {
    res.status(404).json({ error: 'Guest not found' });
    return;
  }

  if (guest.faceId) {
    try {
      await deleteFace(guest.faceId);
    } catch (err: any) {
      // Rekognition deletion failure shouldn't block removing the guest record,
      // but surface it so the operator can manually clean up if needed.
      console.error(`[DELETE /api/guests/${guest.id}] Rekognition deleteFace failed:`, err);
    }
  }

  guestStore.removeGuest(guest.id);
  res.json({ ok: true, removedGuestId: guest.id });
});

// Notification history for a specific guest
router.get('/:id/notifications', (req: Request, res: Response): void => {
  const guest = guestStore.getGuest(req.params.id);
  if (!guest) {
    res.status(404).json({ error: 'Guest not found' });
    return;
  }
  const notifications = guestStore.getNotificationsForGuest(req.params.id);
  res.json({ guestId: req.params.id, notifications });
});

export default router;
