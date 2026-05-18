import nodemailer from 'nodemailer';
import twilio from 'twilio';
import { config } from '../config';
import { Guest, NotificationChannel } from '../types';

// ─── Email ────────────────────────────────────────────────────────────────────

const transporter = nodemailer.createTransport({
  host: config.email.host,
  port: config.email.port,
  secure: config.email.port === 465,
  auth: {
    user: config.email.user,
    pass: config.email.pass,
  },
});

async function sendEmail(guest: Guest, photoPresignedUrl: string): Promise<void> {
  await transporter.sendMail({
    from: `"Wedding Photos 📸" <${config.email.from}>`,
    to: guest.email,
    subject: 'You were spotted at the wedding! 🎉',
    html: `
      <h2>Hi ${guest.name}!</h2>
      <p>We found you in a wedding photo. Click the link below to view and download it:</p>
      <p><a href="${photoPresignedUrl}" style="color:#6366f1;font-weight:bold;">View Your Photo</a></p>
      <p><em>This link expires in 24 hours.</em></p>
      <hr/>
      <p style="color:#888;font-size:12px;">You're receiving this because you registered for wedding photo sharing.</p>
    `,
  });
}

// ─── SMS (Twilio) ─────────────────────────────────────────────────────────────

const twilioClient =
  config.twilio.accountSid && config.twilio.authToken
    ? twilio(config.twilio.accountSid, config.twilio.authToken)
    : null;

async function sendSMS(guest: Guest, photoPresignedUrl: string): Promise<void> {
  if (!twilioClient) throw new Error('Twilio credentials not configured');
  if (!config.twilio.smsFrom) throw new Error('TWILIO_SMS_FROM not configured');

  await twilioClient.messages.create({
    from: config.twilio.smsFrom,
    to: guest.phone,
    body: `Hi ${guest.name}! You were spotted at the wedding 🎉. View your photo: ${photoPresignedUrl}`,
  });
}

// ─── Dispatcher ──────────────────────────────────────────────────────────────

/**
 * Route the notification to the guest's preferred channel.
 * Throws on delivery failure so the caller can log and persist the error.
 */
export async function sendNotification(
  guest: Guest,
  photoPresignedUrl: string,
  channelOverride?: NotificationChannel
): Promise<void> {
  const channel = channelOverride ?? guest.preferredChannel;

  switch (channel) {
    case 'email':
      return sendEmail(guest, photoPresignedUrl);
    case 'sms':
      return sendSMS(guest, photoPresignedUrl);
    case 'line':
      // Line delivery is handled out-of-process by a Solace alert published
      // before this function is called; nothing to do in-band.
      return;
    default:
      throw new Error(`Unknown notification channel: ${channel as string}`);
  }
}
