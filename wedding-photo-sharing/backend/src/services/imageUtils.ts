import sharp from 'sharp';

const REKOGNITION_SUPPORTED = new Set(['image/jpeg', 'image/png']);

/**
 * Convert a buffer to JPEG if the mime type is not supported by Rekognition.
 * Returns the (possibly converted) buffer and the effective mime type.
 * JPEG quality 92 preserves good detail while keeping file size reasonable.
 */
export async function toRekognitionCompatible(
  buffer: Buffer,
  mimeType: string
): Promise<{ buffer: Buffer; mimeType: string }> {
  if (REKOGNITION_SUPPORTED.has(mimeType)) {
    return { buffer, mimeType };
  }
  const converted = await sharp(buffer).jpeg({ quality: 92 }).toBuffer();
  return { buffer: converted, mimeType: 'image/jpeg' };
}
