import { Request, Response, NextFunction } from 'express';
import { NotificationChannel } from '../types';

const VALID_CHANNELS: NotificationChannel[] = ['email', 'line', 'sms'];

/** Validate the body fields required to register a guest. */
export function validateGuestCreate(req: Request, res: Response, next: NextFunction): void {
  const { name, email, phone, preferredChannel } = req.body as Record<string, string>;
  const errors: string[] = [];

  if (!name?.trim()) errors.push('name is required');

  if (!email?.trim()) {
    errors.push('email is required');
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.push('email is invalid');
  }

  if (!phone?.trim()) {
    errors.push('phone is required');
  } else if (!/^\+?[\d\s\-().]{7,20}$/.test(phone)) {
    errors.push('phone must be a valid number (7–20 digits, may start with +)');
  }

  if (!preferredChannel) {
    errors.push('preferredChannel is required');
  } else if (!VALID_CHANNELS.includes(preferredChannel as NotificationChannel)) {
    errors.push(`preferredChannel must be one of: ${VALID_CHANNELS.join(', ')}`);
  }

  if (errors.length > 0) {
    res.status(400).json({ error: 'Validation failed', details: errors.join('; ') });
    return;
  }
  next();
}

/** Ensure at least one file was attached to the request. */
export function validateFilesPresent(req: Request, res: Response, next: NextFunction): void {
  const hasSingle = !!req.file;
  const hasMultiple = Array.isArray(req.files) && req.files.length > 0;

  if (!hasSingle && !hasMultiple) {
    res.status(400).json({ error: 'At least one photo file is required' });
    return;
  }
  next();
}

/** Validate the uploadedBy field for event photo uploads. */
export function validateUploadedBy(req: Request, res: Response, next: NextFunction): void {
  const { uploadedBy } = req.body as Record<string, string>;
  const valid = ['guest', 'photographer', 'admin'];

  if (!uploadedBy || !valid.includes(uploadedBy)) {
    res.status(400).json({
      error: `uploadedBy must be one of: ${valid.join(', ')}`,
    });
    return;
  }
  next();
}
