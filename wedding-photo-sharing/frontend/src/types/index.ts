export type NotificationChannel = 'email' | 'line' | 'sms';

export interface Guest {
  id: string;
  name: string;
  email: string;
  phone: string;
  preferredChannel: NotificationChannel;
  faceId?: string;
  referencePhotoKey?: string;
  // Presigned URL for the reference photo. Generated server-side per request,
  // expires in 24h. Absent if the guest has no reference photo on S3.
  referencePhotoUrl?: string;
  createdAt: string;
}

export interface RecognitionMatch {
  guestId: string;
  guestName: string;
  confidence: number;
}

export interface RecognitionResult {
  photoId: string;
  s3Key: string;
  matches: RecognitionMatch[];
  processedAt: string;
}

export interface UploadPhotoResult {
  photo: {
    id: string;
    s3Key: string;
    s3Url: string;
    originalName: string;
  };
  recognition: RecognitionResult;
  notifiedGuests: string[];
}

export interface UploadPhotosResponse {
  processed: number;
  results: UploadPhotoResult[];
}

export interface StatusStats {
  registeredGuests: number;
  guestsWithFaceIndex: number;
  totalPhotosUploaded: number;
  eventPhotos: number;
  referencePhotos: number;
  recognitionResults: number;
  totalMatchesFound: number;
  notificationsSent: number;
  notificationsFailed: number;
}

export interface ApiError {
  error: string;
  details?: string;
}
