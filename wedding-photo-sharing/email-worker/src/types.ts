// Mirror of SolaceAlertPayload on the backend. Kept inline so the worker has
// no compile-time dependency on the backend package.
export interface EmailAlertPayload {
  payload: {
    guestName: string;
    contactMethod: {
      channel: 'email' | 'line' | 'sms';
      value: string;
    };
    photoUrl: string;
    photoPresignedUrl: string;
    // Full presigned URL for inline <img>. Falls back to photoPresignedUrl
    // for older messages that don't include this field.
    photoImageUrl?: string;
  };
}
