import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import { config } from './config';
import { ensureCollection } from './services/rekognitionService';
import { ensureBucket } from './services/s3Service';
import { connectSolace, disconnectSolace } from './services/solaceService';
import guestRoutes from './routes/guests';
import photoRoutes from './routes/photos';
import statusRoutes from './routes/status';
import adminRoutes from './routes/admin';

const app = express();

// ─── Middleware ───────────────────────────────────────────────────────────────

app.use(
  cors({
    origin: config.frontendOrigin,
    methods: ['GET', 'POST', 'DELETE'],
    allowedHeaders: ['Content-Type'],
  })
);
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ─── Routes ───────────────────────────────────────────────────────────────────

app.use('/api/guests', guestRoutes);
app.use('/api/upload-photos', photoRoutes);
app.use('/api/status', statusRoutes);
app.use('/api/admin', adminRoutes);

// Root health check
app.get('/', (_req: Request, res: Response) => {
  res.json({ message: 'Wedding Photo API is running' });
});

// ─── Error handler ────────────────────────────────────────────────────────────

// Multer errors (file size, file type) bubble up with a specific status
app.use((err: any, _req: Request, res: Response, _next: NextFunction) => {
  if (err.code === 'LIMIT_FILE_SIZE') {
    res.status(413).json({ error: 'File too large. Maximum size is 20 MB.' });
    return;
  }
  console.error('[Unhandled error]', err);
  res.status(500).json({ error: err.message ?? 'Internal server error' });
});

// ─── Startup ──────────────────────────────────────────────────────────────────

async function start() {
  // Ensure S3 bucket exists (creates it if missing)
  try {
    await ensureBucket();
  } catch (err) {
    console.warn('[Startup] S3 bucket check failed (continuing):', err);
  }

  // Ensure AWS Rekognition collection exists before accepting requests
  try {
    await ensureCollection();
  } catch (err) {
    console.warn('[Startup] Rekognition collection check failed (continuing):', err);
  }

  // Connect to Solace broker (non-fatal if unavailable)
  try {
    await connectSolace();
  } catch (err) {
    console.warn('[Startup] Solace connection failed (continuing without broker):', err);
  }

  const server = app.listen(config.port, () => {
    console.log(`[Server] Listening on http://localhost:${config.port}`);
  });

  // Graceful shutdown
  const shutdown = async () => {
    console.log('[Server] Shutting down…');
    disconnectSolace();
    server.close(() => process.exit(0));
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

start().catch((err) => {
  console.error('[Startup] Fatal error:', err);
  process.exit(1);
});

export default app; // exported for testing
