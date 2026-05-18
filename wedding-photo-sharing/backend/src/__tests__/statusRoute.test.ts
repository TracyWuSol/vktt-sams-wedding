/**
 * Integration test for GET /api/status.
 * AWS, Solace, and Twilio are mocked so the test runs without credentials.
 */

// Mock external services before importing the app
jest.mock('../services/rekognitionService', () => ({
  ensureCollection: jest.fn().mockResolvedValue(undefined),
}));
jest.mock('../services/solaceService', () => ({
  connectSolace: jest.fn().mockResolvedValue(undefined),
  disconnectSolace: jest.fn(),
  publishPhotoUploaded: jest.fn(),
  publishRecognitionCompleted: jest.fn(),
  publishNotificationSend: jest.fn(),
}));

import request from 'supertest';
import type { Application } from 'express';

// Dynamically import app AFTER mocks are in place
let app: Application;

beforeAll(async () => {
  // Need a dynamic require here because the app calls connectSolace/ensureCollection at module load
  // We silence the startup output
  jest.spyOn(console, 'log').mockImplementation(() => {});
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  const mod = await import('../index');
  app = (mod as any).default;
});

afterAll(() => {
  jest.restoreAllMocks();
});

describe('GET /api/status', () => {
  it('returns 200 with stats object', async () => {
    const res = await request(app).get('/api/status');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
    expect(res.body.stats).toMatchObject({
      registeredGuests: expect.any(Number),
      eventPhotos: expect.any(Number),
      notificationsSent: expect.any(Number),
    });
  });
});

describe('GET /', () => {
  it('returns health message', async () => {
    const res = await request(app).get('/');
    expect(res.status).toBe(200);
    expect(res.body.message).toMatch(/running/i);
  });
});
