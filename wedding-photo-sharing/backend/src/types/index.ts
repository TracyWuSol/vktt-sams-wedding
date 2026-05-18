export type NotificationChannel = 'email' | 'line' | 'sms';

export interface Guest {
  id: string;
  name: string;
  email: string;
  phone: string;
  preferredChannel: NotificationChannel;
  // AWS Rekognition face ID assigned after indexing the reference photo
  faceId?: string;
  referencePhotoKey?: string; // S3 object key of the reference photo
  createdAt: string;
}

export interface GuestCreateInput {
  name: string;
  email: string;
  phone: string;
  preferredChannel: NotificationChannel;
}

export interface UploadedPhoto {
  id: string;
  s3Key: string;
  s3Url: string;
  uploadedBy: 'admin' | 'guest' | 'photographer';
  uploadType: 'reference' | 'event';
  uploadedAt: string;
  originalName: string;
  mimeType: string;
  sizeBytes: number;
}

export interface RecognitionMatch {
  guestId: string;
  guestName: string;
  confidence: number; // 0–100
}

export interface RecognitionResult {
  photoId: string;
  s3Key: string;
  matches: RecognitionMatch[];
  processedAt: string;
}

export interface NotificationRecord {
  id: string;
  guestId: string;
  channel: NotificationChannel;
  photoS3Key: string;
  status: 'sent' | 'failed';
  sentAt: string;
  error?: string;
}

// Solace message payloads — kept flat for easy JSON serialisation
export interface SolacePhotoUploadedPayload {
  photoId: string;
  s3Key: string;
  uploadType: 'reference' | 'event';
  uploadedBy: string;
  guestId?: string; // populated for reference photos
  timestamp: string;
}

export interface SolaceRecognitionCompletedPayload {
  photoId: string;
  s3Key: string;
  matches: RecognitionMatch[];
  timestamp: string;
}

export interface SolaceNotificationPayload {
  guestId: string;
  channel: NotificationChannel;
  photoS3Key: string;
  photoPresignedUrl: string;
  timestamp: string;
}

export interface SolaceAlertPayload {
  payload: {
    guestName: string;
    contactMethod: {
      channel: NotificationChannel;
      value: string;
    };
    photoUrl: string;
    photoPresignedUrl: string;
    // Full presigned URL (not shortened). Suitable for use as an <img src> in
    // email — most clients do not follow redirects for image fetches, so the
    // shortener URL would render as a broken image.
    photoImageUrl?: string;
  };
}

export interface ApiError {
  error: string;
  details?: string;
}
