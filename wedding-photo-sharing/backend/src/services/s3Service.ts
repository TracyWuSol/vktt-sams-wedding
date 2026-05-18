import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
  CreateBucketCommand,
  HeadBucketCommand,
  BucketLocationConstraint,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { config } from '../config';

const s3 = new S3Client({
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
    : {}), // falls back to IAM role / environment credentials when keys are absent
});

/**
 * Ensure the S3 bucket exists, creating it if necessary.
 * Called once at server startup — safe to call repeatedly.
 * Note: us-east-1 must NOT include a LocationConstraint (AWS quirk).
 */
export async function ensureBucket(): Promise<void> {
  try {
    await s3.send(new HeadBucketCommand({ Bucket: config.aws.s3Bucket }));
    console.log(`[S3] Bucket exists: ${config.aws.s3Bucket}`);
  } catch (err: any) {
    if (err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
      const createParams: ConstructorParameters<typeof CreateBucketCommand>[0] = {
        Bucket: config.aws.s3Bucket,
      };
      if (config.aws.region !== 'us-east-1') {
        createParams.CreateBucketConfiguration = {
          LocationConstraint: config.aws.region as BucketLocationConstraint,
        };
      }
      await s3.send(new CreateBucketCommand(createParams));
      console.log(`[S3] Created bucket: ${config.aws.s3Bucket} in ${config.aws.region}`);
    } else {
      throw err;
    }
  }
}

/**
 * Upload a JSON metadata object to S3 under the "metadata/" prefix.
 * Key structure: metadata/{guestId}/{photoId}.json
 * This is picked up by the Solace Micro-integration for S3 which publishes
 * to topic wedding/alerts/{guestId}/{photoId}.
 */
export async function uploadMetadataToS3(metadata: object, metadataKey: string): Promise<void> {
  await s3.send(
    new PutObjectCommand({
      Bucket: config.aws.s3Bucket,
      Key: metadataKey,
      Body: JSON.stringify(metadata, null, 2),
      ContentType: 'application/json',
      ServerSideEncryption: 'AES256',
    })
  );
}

/**
 * Upload a file buffer to S3 and return the resulting object key.
 * Keys are namespaced by upload type so IAM policies can be scoped per folder.
 */
export async function uploadToS3(
  buffer: Buffer,
  originalName: string,
  mimeType: string,
  folder: 'references' | 'events',
  objectId: string
): Promise<string> {
  const extension = originalName.split('.').pop() ?? 'jpg';
  const key = `${folder}/${objectId}.${extension}`;

  await s3.send(
    new PutObjectCommand({
      Bucket: config.aws.s3Bucket,
      Key: key,
      Body: buffer,
      ContentType: mimeType,
      // Server-side encryption at rest
      ServerSideEncryption: 'AES256',
    })
  );

  return key;
}

/**
 * Generate a presigned URL so recipients can download the photo without
 * making the S3 bucket public.  Default expiry is 24 hours.
 */
export async function getPresignedUrl(s3Key: string, expiresInSeconds = 86400): Promise<string> {
  const command = new GetObjectCommand({
    Bucket: config.aws.s3Bucket,
    Key: s3Key,
  });
  return getSignedUrl(s3, command, { expiresIn: expiresInSeconds });
}

export async function deleteFromS3(s3Key: string): Promise<void> {
  await s3.send(
    new DeleteObjectCommand({
      Bucket: config.aws.s3Bucket,
      Key: s3Key,
    })
  );
}

/** Return the public S3 URL (only useful when the bucket/object is public). */
export function buildS3Url(s3Key: string): string {
  return `https://${config.aws.s3Bucket}.s3.${config.aws.region}.amazonaws.com/${s3Key}`;
}
