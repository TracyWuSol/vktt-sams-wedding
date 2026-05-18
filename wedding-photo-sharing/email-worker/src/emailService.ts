import nodemailer from 'nodemailer';
import { config } from './config';
import { EmailAlertPayload } from './types';

const transporter = nodemailer.createTransport({
  host: config.email.host,
  port: config.email.port,
  secure: config.email.port === 465,
  auth: {
    user: config.email.user,
    pass: config.email.pass,
  },
});

export async function sendEmailFromAlert(alert: EmailAlertPayload): Promise<void> {
  const { guestName, contactMethod, photoPresignedUrl } = alert.payload;

  if (contactMethod.channel !== 'email') {
    throw new Error(`Unexpected channel for email-worker: ${contactMethod.channel}`);
  }
  if (!contactMethod.value) {
    throw new Error('Alert payload missing recipient email');
  }

  const imageSrc = alert.payload.photoImageUrl ?? photoPresignedUrl;

  const info = await transporter.sendMail({
    from: `"Wedding Photos" <${config.email.from}>`,
    to: contactMethod.value,
    subject: 'You were spotted at the wedding!',
    html: `
      <div style="max-width:560px;margin:0 auto;font-family:Georgia,'Times New Roman',serif;color:#2a2030;background:#fbf7f1;padding:32px 28px;border:1px solid #ecd9b6;border-radius:14px;">
        <div style="text-align:center;font-size:13px;letter-spacing:6px;color:#b08a4a;text-transform:uppercase;margin-bottom:6px;">&#10047; &nbsp; A Memory For You &nbsp; &#10047;</div>
        <h2 style="text-align:center;font-weight:400;font-size:26px;margin:0 0 18px;color:#3a2d4a;">Hi ${guestName},</h2>
        <p style="text-align:center;font-size:15px;line-height:1.55;margin:0 0 22px;">We spotted you in a wedding photo. A little keepsake from the day &mdash; tap the image to view it full size.</p>
        <a href="${photoPresignedUrl}" style="display:block;text-decoration:none;">
          <img src="${imageSrc}" alt="Your wedding photo" style="display:block;width:100%;max-width:560px;height:auto;border-radius:10px;border:1px solid #ecd9b6;" />
        </a>
        <div style="text-align:center;margin:24px 0 8px;">
          <a href="${photoPresignedUrl}" style="display:inline-block;background:#b08a4a;color:#fff;text-decoration:none;padding:11px 26px;border-radius:30px;font-size:14px;letter-spacing:1px;font-family:Georgia,'Times New Roman',serif;">View &amp; Download</a>
        </div>
        <p style="text-align:center;font-size:12px;color:#8c7a64;margin:6px 0 18px;font-style:italic;">This link is valid for 24 hours.</p>
        <hr style="border:none;border-top:1px solid #ecd9b6;margin:18px 0;" />
        <p style="text-align:center;font-size:11px;color:#a89a82;margin:0;">You're receiving this because you registered for wedding photo sharing. &#10084;</p>
      </div>
    `,
  });

  console.log(
    `[Email][SMTP] to=${contactMethod.value} messageId=${info.messageId} accepted=${JSON.stringify(info.accepted)} rejected=${JSON.stringify(info.rejected)} response=${info.response}`
  );
}
