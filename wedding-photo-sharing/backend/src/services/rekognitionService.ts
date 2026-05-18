import {
  RekognitionClient,
  CreateCollectionCommand,
  IndexFacesCommand,
  SearchFacesByImageCommand,
  DetectFacesCommand,
  DeleteFacesCommand,
  DeleteCollectionCommand,
  DescribeCollectionCommand,
  ListFacesCommand,
} from '@aws-sdk/client-rekognition';
import sharp from 'sharp';
import { config } from '../config';

const rek = new RekognitionClient({
  region: config.aws.region,
  ...(config.aws.accessKeyId && config.aws.secretAccessKey
    ? {
        credentials: {
          accessKeyId: config.aws.accessKeyId,
          secretAccessKey: config.aws.secretAccessKey,
          // sessionToken is required for temporary STS credentials (ASIA... keys).
          // Disable via AWS_USE_SESSION_TOKEN=false when using permanent AKIA keys.
          ...(config.aws.useSessionToken && config.aws.sessionToken
            ? { sessionToken: config.aws.sessionToken }
            : {}),
        },
      }
    : {}),
});

const COLLECTION_ID = config.aws.rekognitionCollection;

// Padding added around each detected bounding box before cropping.
// 15 % ensures the full face (including forehead/chin) is included.
const CROP_PADDING = 0.15;

// Discard face crops smaller than this — Rekognition rejects tiny images.
const MIN_CROP_PX = 40;

/**
 * Ensure the Rekognition face collection exists.
 * Called once at server startup; safe to call repeatedly.
 */
export async function ensureCollection(): Promise<void> {
  try {
    await rek.send(new DescribeCollectionCommand({ CollectionId: COLLECTION_ID }));
  } catch (err: any) {
    if (err.name === 'ResourceNotFoundException') {
      await rek.send(new CreateCollectionCommand({ CollectionId: COLLECTION_ID }));
      console.log(`[Rekognition] Created collection: ${COLLECTION_ID}`);
    } else {
      throw err;
    }
  }
}

/**
 * Delete and recreate the Rekognition collection, wiping all indexed faces.
 * Used when the guest store is reset so stale face IDs don't cause mismatches.
 */
export async function purgeCollection(): Promise<void> {
  try {
    await rek.send(new DeleteCollectionCommand({ CollectionId: COLLECTION_ID }));
    console.log(`[Rekognition] Deleted collection: ${COLLECTION_ID}`);
  } catch (err: any) {
    if (err.name !== 'ResourceNotFoundException') throw err;
  }
  await rek.send(new CreateCollectionCommand({ CollectionId: COLLECTION_ID }));
  console.log(`[Rekognition] Recreated collection: ${COLLECTION_ID}`);
}

/**
 * Return all face IDs currently indexed in the collection.
 * Useful for diagnosing stale-face mismatches.
 */
export async function listIndexedFaces(): Promise<{ faceId: string; externalImageId: string }[]> {
  const faces: { faceId: string; externalImageId: string }[] = [];
  let nextToken: string | undefined;
  do {
    const response = await rek.send(
      new ListFacesCommand({ CollectionId: COLLECTION_ID, NextToken: nextToken, MaxResults: 100 })
    );
    for (const face of response.Faces ?? []) {
      faces.push({ faceId: face.FaceId ?? '', externalImageId: face.ExternalImageId ?? '' });
    }
    nextToken = response.NextToken;
  } while (nextToken);
  return faces;
}

/**
 * Index a face from a reference photo stored in S3.
 * Returns the Rekognition FaceId assigned to this person.
 * Only the largest detected face is indexed (MaxFaces=1) to keep
 * reference entries unambiguous.
 */
export async function indexGuestFace(s3Key: string, externalImageId: string): Promise<string> {
  const response = await rek.send(
    new IndexFacesCommand({
      CollectionId: COLLECTION_ID,
      Image: {
        S3Object: {
          Bucket: config.aws.s3Bucket,
          Name: s3Key,
        },
      },
      ExternalImageId: externalImageId, // we store the guestId here for easy lookup
      MaxFaces: 1,
      QualityFilter: 'AUTO',
      DetectionAttributes: ['DEFAULT'],
    })
  );

  const faceRecord = response.FaceRecords?.[0];
  if (!faceRecord?.Face?.FaceId) {
    throw new Error('No face detected in the reference photo');
  }
  return faceRecord.Face.FaceId;
}

export interface FaceMatch {
  faceId: string;
  externalImageId: string; // the guestId stored as ExternalImageId during indexing
  confidence: number;
}

/**
 * Detect and identify every face in a group photo.
 *
 * Flow:
 *   1. DetectFaces  → bounding boxes for all faces in the image
 *   2. sharp        → crop each face (with padding) into a JPEG buffer
 *   3. SearchFacesByImage (Bytes) → match each crop against the collection
 *
 * Using per-crop Bytes avoids the AWS limitation where SearchFacesByImage
 * only searches against the single largest face when given a full-image S3 key.
 * Results are deduplicated so each guest appears at most once (highest confidence wins).
 */
export async function searchAllFacesInPhoto(
  imageBuffer: Buffer,
  minConfidence = 80
): Promise<FaceMatch[]> {
  // Step 1: locate every face bounding box
  const detectResponse = await rek.send(
    new DetectFacesCommand({
      Image: { Bytes: imageBuffer },
      Attributes: ['DEFAULT'],
    })
  );

  const faceDetails = detectResponse.FaceDetails ?? [];
  if (faceDetails.length === 0) {
    console.log('[Rekognition] No faces detected in photo');
    return [];
  }

  console.log(`[Rekognition] Detected ${faceDetails.length} face(s) — searching collection…`);

  // Step 2: get pixel dimensions once for coordinate conversion
  const { width: imgW = 0, height: imgH = 0 } = await sharp(imageBuffer).metadata();

  // Map: guestId → best match so far (deduplication across multiple crops)
  const bestByGuest = new Map<string, FaceMatch>();

  // Step 3: crop each face and search the collection
  for (let i = 0; i < faceDetails.length; i++) {
    const box = faceDetails[i].BoundingBox;
    if (!box) continue;

    // Expand bounding box by CROP_PADDING on each side, clamped to image bounds
    const rawLeft   = (box.Left   ?? 0) - CROP_PADDING * (box.Width  ?? 0);
    const rawTop    = (box.Top    ?? 0) - CROP_PADDING * (box.Height ?? 0);
    const rawWidth  = (box.Width  ?? 0) * (1 + 2 * CROP_PADDING);
    const rawHeight = (box.Height ?? 0) * (1 + 2 * CROP_PADDING);

    const left   = Math.max(0, Math.round(rawLeft   * imgW));
    const top    = Math.max(0, Math.round(rawTop    * imgH));
    const width  = Math.min(imgW - left, Math.round(rawWidth  * imgW));
    const height = Math.min(imgH - top,  Math.round(rawHeight * imgH));

    if (width < MIN_CROP_PX || height < MIN_CROP_PX) {
      console.log(`[Rekognition] Face ${i + 1} crop too small (${width}×${height}px) — skipping`);
      continue;
    }

    let croppedBuffer: Buffer;
    try {
      croppedBuffer = await sharp(imageBuffer)
        .extract({ left, top, width, height })
        .jpeg({ quality: 92 })
        .toBuffer();
    } catch (cropErr: any) {
      console.warn(`[Rekognition] Crop failed for face ${i + 1}:`, cropErr.message);
      continue;
    }

    try {
      const searchResponse = await rek.send(
        new SearchFacesByImageCommand({
          CollectionId: COLLECTION_ID,
          Image: { Bytes: croppedBuffer },
          FaceMatchThreshold: minConfidence,
          MaxFaces: 1, // crop is already isolated to one face
        })
      );

      for (const match of searchResponse.FaceMatches ?? []) {
        const guestId    = match.Face?.ExternalImageId ?? '';
        const faceId     = match.Face?.FaceId ?? '';
        const confidence = match.Similarity ?? 0;

        if (!guestId) continue;

        const existing = bestByGuest.get(guestId);
        if (!existing || confidence > existing.confidence) {
          bestByGuest.set(guestId, { faceId, externalImageId: guestId, confidence });
        }
      }
    } catch (searchErr: any) {
      // InvalidParameterException = no indexable face in crop (too blurry, profile, etc.)
      if (searchErr.name !== 'InvalidParameterException') {
        console.warn(`[Rekognition] Search error for face ${i + 1}:`, searchErr.message);
      }
    }
  }

  const matches = Array.from(bestByGuest.values());
  console.log(`[Rekognition] Matched ${matches.length} guest(s) in photo`);
  return matches;
}

export async function deleteFace(faceId: string): Promise<void> {
  await rek.send(
    new DeleteFacesCommand({
      CollectionId: COLLECTION_ID,
      FaceIds: [faceId],
    })
  );
}
