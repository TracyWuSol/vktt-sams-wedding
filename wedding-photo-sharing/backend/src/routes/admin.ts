/**
 * Admin utility routes.
 *
 * POST /api/admin/reset  — wipe Rekognition collection + guest store so
 *                          guests can be re-registered without stale face IDs
 * GET  /api/admin/faces  — list all faces currently indexed in Rekognition
 *                          (useful for diagnosing stale-face mismatches)
 */
import { Router, Request, Response } from 'express';
import fs from 'fs';
import path from 'path';
import { purgeCollection, listIndexedFaces } from '../services/rekognitionService';
import { guestStore } from '../store/guestStore';

const router = Router();

const GUESTS_FILE = path.resolve(__dirname, '../../data/guests.json');

router.post('/reset', async (_req: Request, res: Response): Promise<void> => {
  try {
    // 1. Wipe Rekognition collection (delete + recreate)
    await purgeCollection();

    // 2. Clear guests.json on disk
    if (fs.existsSync(GUESTS_FILE)) {
      fs.writeFileSync(GUESTS_FILE, JSON.stringify([], null, 2));
    }

    // 3. Wipe both the on-disk file and the in-memory store
    fs.writeFileSync(GUESTS_FILE, JSON.stringify([], null, 2));
    guestStore.clearAll();

    res.json({
      ok: true,
      message: 'Rekognition collection purged and guest store cleared. Please re-register all guests.',
    });
  } catch (err: any) {
    console.error('[POST /api/admin/reset] Error:', err);
    res.status(500).json({ error: 'Reset failed', details: err.message });
  }
});

router.get('/faces', async (_req: Request, res: Response): Promise<void> => {
  try {
    const faces = await listIndexedFaces();
    const guests = guestStore.getAllGuests().map((g) => ({ id: g.id, name: g.name, faceId: g.faceId }));
    res.json({ indexedFaces: faces, registeredGuests: guests });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
