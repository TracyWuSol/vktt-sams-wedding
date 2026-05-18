import multer from 'multer';
import { RequestHandler } from 'express';

const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic'];
const MAX_FILE_SIZE_MB = 20;

const storage = multer.memoryStorage(); // keep files in-memory for direct S3 streaming

const fileFilter: multer.Options['fileFilter'] = (_req, file, cb) => {
  if (ALLOWED_MIME_TYPES.includes(file.mimetype)) {
    cb(null, true);
  } else {
    cb(new Error(`Unsupported file type: ${file.mimetype}. Allowed: JPEG, PNG, WebP, HEIC`));
  }
};

const upload = multer({
  storage,
  fileFilter,
  limits: {
    fileSize: MAX_FILE_SIZE_MB * 1024 * 1024,
    files: 10, // max files per request
  },
});

/** Single-file upload field named "photo" */
export const uploadSingle: RequestHandler = upload.single('photo');

/** Multi-file upload field named "photos" (up to 10 files) */
export const uploadMultiple: RequestHandler = upload.array('photos', 10);
