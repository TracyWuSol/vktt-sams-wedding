import dotenv from 'dotenv';
dotenv.config();

function required(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Missing required env var: ${key}`);
  return value;
}

function optional(key: string, fallback: string): string {
  return process.env[key] ?? fallback;
}

export const config = {
  port: parseInt(optional('PORT', '4000'), 10),

  aws: {
    region: optional('AWS_REGION', 'us-east-1'),
    accessKeyId: optional('AWS_ACCESS_KEY_ID', ''),
    secretAccessKey: optional('AWS_SECRET_ACCESS_KEY', ''),
    // Required when using temporary STS credentials (keys starting with ASIA).
    // Set AWS_USE_SESSION_TOKEN=false to ignore it (e.g. with permanent AKIA keys).
    sessionToken: optional('AWS_SESSION_TOKEN', ''),
    useSessionToken: optional('AWS_USE_SESSION_TOKEN', 'true').toLowerCase() !== 'false',
    s3Bucket: optional('AWS_S3_BUCKET', 'wedding-photos-demo'),
    rekognitionCollection: optional('AWS_REKOGNITION_COLLECTION', 'wedding-guests'),
  },

  // Solace PubSub+ broker connection settings
  solace: {
    host: optional('SOLACE_HOST', 'tcps://mr-connection.messaging.solace.cloud:55443'),
    vpnName: optional('SOLACE_VPN_NAME', 'default'),
    username: optional('SOLACE_USERNAME', 'admin'),
    password: optional('SOLACE_PASSWORD', 'password'),
    // Topics follow a hierarchical pattern for routing flexibility
    topics: {
      photoUploaded: 'wedding/s3/photos/uploaded',
      guestRegistered: 'wedding/guests/registered',
      recognitionCompleted: 'wedding/recognition/completed',
      notificationSend: 'wedding/notifications/send',
    },
  },

  email: {
    host: optional('EMAIL_HOST', 'smtp.gmail.com'),
    port: parseInt(optional('EMAIL_PORT', '587'), 10),
    user: optional('EMAIL_USER', ''),
    pass: optional('EMAIL_PASS', ''),
    from: optional('EMAIL_FROM', 'wedding@example.com'),
  },

  // Twilio credentials for SMS delivery
  twilio: {
    accountSid: optional('TWILIO_ACCOUNT_SID', ''),
    authToken: optional('TWILIO_AUTH_TOKEN', ''),
    smsFrom: optional('TWILIO_SMS_FROM', ''),
  },

  frontendOrigin: optional('FRONTEND_ORIGIN', 'http://localhost:5173'),
};
