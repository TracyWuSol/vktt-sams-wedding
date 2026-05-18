/**
 * Photo upload routes for guests and photographers.
 *
 * POST /api/upload-photos  – upload one or more event photos; triggers
 *                            facial recognition and guest notifications
 * GET  /api/upload-photos  – list all uploaded event photos
 * GET  /api/upload-photos/:id/result – recognition result for a photo
 */
import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { uploadMultiple } from '../middleware/upload';
import { validateFilesPresent, validateUploadedBy } from '../middleware/validation';
import { uploadToS3, getPresignedUrl, buildS3Url, uploadMetadataToS3 } from '../services/s3Service';
import { searchAllFacesInPhoto } from '../services/rekognitionService';
import { toRekognitionCompatible } from '../services/imageUtils';
import {
  publishPhotoUploaded,
  publishRecognitionCompleted,
  publishNotificationSend,
  publishAlert,
  publishEmailAlert,
  publishLineAlert,
} from '../services/solaceService';
import { sendNotification } from '../services/notificationService';
import { shortenUrl } from '../services/urlShortenerService';
import { guestStore } from '../store/guestStore';
import { UploadedPhoto, RecognitionResult, NotificationRecord } from '../types';

const router = Router();

// Upload event photos, run facial recognition, notify matched guests
router.post(
  '/',
  uploadMultiple,
  validateFilesPresent,
  validateUploadedBy,
  async (req: Request, res: Response): Promise<void> => {
    const files = req.files as Express.Multer.File[];
    const { uploadedBy } = req.body as { uploadedBy: 'guest' | 'photographer' | 'admin' };

    const results: {
      photo: UploadedPhoto;
      recognition: RecognitionResult;
      notifiedGuests: string[];
    }[] = [];

    for (const file of files) {
      const photoId = uuidv4();
      const now = new Date().toISOString();

      try {
        // Convert to JPEG if needed — Rekognition only accepts JPEG and PNG
        const { buffer, mimeType } = await toRekognitionCompatible(file.buffer, file.mimetype);

        // 1. Upload to S3 under the "events/" prefix (store the Rekognition-compatible version)
        const s3Key = await uploadToS3(
          buffer,
          mimeType === 'image/jpeg' ? `${photoId}.jpg` : file.originalname,
          mimeType,
          'events',
          photoId
        );

        const photo: UploadedPhoto = {
          id: photoId,
          s3Key,
          s3Url: buildS3Url(s3Key),
          uploadedBy,
          uploadType: 'event',
          uploadedAt: now,
          originalName: file.originalname,
          mimeType,
          sizeBytes: buffer.length,
        };
        guestStore.addPhoto(photo);

        // 2. Notify Solace that a new event photo arrived in S3
        publishPhotoUploaded({
          photoId,
          s3Key,
          uploadType: 'event',
          uploadedBy,
          timestamp: now,
        });

        // 3. Detect and identify all faces in the photo against the collection
        const faceMatches = await searchAllFacesInPhoto(buffer);

        console.log('[DEBUG] faceMatches returned:', JSON.stringify(faceMatches));
        console.log('[DEBUG] guests in store:', JSON.stringify(
          guestStore.getAllGuests().map(g => ({ id: g.id, faceId: g.faceId }))
        ));

        const recognitionResult: RecognitionResult = {
          photoId,
          s3Key,
          matches: faceMatches
            .map((m) => {
              const byFaceId = guestStore.findByFaceId(m.faceId);
              const byGuestId = guestStore.getGuest(m.externalImageId);
              console.log(`[DEBUG] match faceId=${m.faceId} extId=${m.externalImageId} -> byFaceId=${byFaceId?.name} byGuestId=${byGuestId?.name}`);
              const guest = byFaceId ?? byGuestId;
              return guest
                ? { guestId: guest.id, guestName: guest.name, confidence: m.confidence }
                : null;
            })
            .filter(Boolean) as RecognitionResult['matches'],
          processedAt: new Date().toISOString(),
        };
        guestStore.addRecognitionResult(recognitionResult);

        // 4. Publish recognition result to Solace
        publishRecognitionCompleted({
          photoId,
          s3Key,
          matches: recognitionResult.matches,
          timestamp: recognitionResult.processedAt,
        });

        // 5. Send notifications to each matched guest
        const presignedUrl = await getPresignedUrl(s3Key);
        const shortPresignedUrl = await shortenUrl(presignedUrl);
        const notifiedGuests: string[] = [];

        for (const match of recognitionResult.matches) {
          const guest = guestStore.getGuest(match.guestId);
          if (!guest) continue;

          // Drop a notification payload JSON in S3 so the Solace S3 micro-integration
          // (or any other downstream consumer) can pick it up and dispatch the notification.
          const notificationKey = `notification/${guest.id}_${photoId}.json`;
          await uploadMetadataToS3(
            {
              payload: {
                guestName: guest.name,
                photoUrl: presignedUrl,
                email: guest.email,
                phone: guest.phone,
                channel: guest.preferredChannel,
              },
            },
            notificationKey
          ).catch((err: any) => console.error(`[Notification S3] Failed to upload ${notificationKey}:`, err));

          const alertPayload = {
            payload: {
              guestName: guest.name,
              contactMethod: {
                channel: guest.preferredChannel,
                value: guest.preferredChannel === 'email' ? guest.email : guest.phone,
              },
              photoUrl: photo.s3Url,
              photoPresignedUrl: shortPresignedUrl,
              photoImageUrl: presignedUrl,
            },
          };

          // Publish the alert directly to Solace on wedding/alerts/{guestId}/{photoId}
          publishAlert(guest.id, photoId, alertPayload);

          // Publish the intent to send a notification via Solace before actually sending
          publishNotificationSend({
            guestId: guest.id,
            channel: guest.preferredChannel,
            photoS3Key: s3Key,
            photoPresignedUrl: presignedUrl,
            timestamp: new Date().toISOString(),
          });

          let notifStatus: NotificationRecord['status'] = 'sent';
          let notifError: string | undefined;

          try {
            if (guest.preferredChannel === 'email') {
              // Email delivery is handled out-of-process by the email-worker,
              // which binds to a queue subscribed to `wedding/alerts/photos/email/>`.
              publishEmailAlert(guest.id, photoId, alertPayload);
            } else if (guest.preferredChannel === 'line') {
              // Line delivery is handled out-of-process by a future line-worker
              // bound to `wedding/alerts/photos/line/>`.
              publishLineAlert(guest.id, photoId, alertPayload);
            } else {
              await sendNotification(guest, presignedUrl);
            }
            notifiedGuests.push(guest.name);
          } catch (notifErr: any) {
            console.error(`[Notification] Failed for guest ${guest.id}:`, notifErr);
            notifStatus = 'failed';
            notifError = notifErr.message;
          }

          const notifRecord: NotificationRecord = {
            id: uuidv4(),
            guestId: guest.id,
            channel: guest.preferredChannel,
            photoS3Key: s3Key,
            status: notifStatus,
            sentAt: new Date().toISOString(),
            ...(notifError && { error: notifError }),
          };
          guestStore.addNotification(notifRecord);
        }

        results.push({ photo, recognition: recognitionResult, notifiedGuests });

        // Upload one metadata JSON per matched guest so the Solace Micro-integration
        // for S3 can publish to wedding/alerts/{guestId}/{photoId}
        const baseMetadata = {
          photoId,
          s3Key,
          s3Url: photo.s3Url,
          originalName: file.originalname,
          mimeType,
          sizeBytes: buffer.length,
          uploadedBy,
          uploadType: 'event',
          uploadedAt: now,
        };

        if (recognitionResult.matches.length > 0) {
          for (const match of recognitionResult.matches) {
            const metadataKey = `metadata/${match.guestId}/${photoId}.json`;
            await uploadMetadataToS3(
              { ...baseMetadata, guestId: match.guestId, guestName: match.guestName, confidence: match.confidence },
              metadataKey
            ).catch((err: any) => console.error(`[Metadata] Failed to upload ${metadataKey}:`, err));
          }
        } else {
          const metadataKey = `metadata/unmatched/${photoId}.json`;
          await uploadMetadataToS3(baseMetadata, metadataKey)
            .catch((err: any) => console.error(`[Metadata] Failed to upload ${metadataKey}:`, err));
        }
      } catch (err: any) {
        console.error(`[POST /api/upload-photos] Error processing ${file.originalname}:`, err);
        // Continue processing remaining files; report per-file errors in response
        results.push({
          photo: {
            id: photoId,
            s3Key: '',
            s3Url: '',
            uploadedBy,
            uploadType: 'event',
            uploadedAt: now,
            originalName: file.originalname,
            mimeType: file.mimetype,
            sizeBytes: file.size,
          },
          recognition: { photoId, s3Key: '', matches: [], processedAt: now },
          notifiedGuests: [],
        });
      }
    }

    res.status(202).json({ processed: results.length, results });
  }
);

// List all event photos
router.get('/', (_req, res: Response): void => {
  const photos = guestStore.getAllPhotos().filter((p) => p.uploadType === 'event');
  res.json({ photos });
});

// Get recognition result for a specific photo
router.get('/:id/result', (req: Request, res: Response): void => {
  const result = guestStore.getRecognitionResult(req.params.id);
  if (!result) {
    res.status(404).json({ error: 'Recognition result not found for this photo ID' });
    return;
  }
  res.json({ result });
});

export default router;
