import { Request, Response, NextFunction } from 'express';
import {
  validateGuestCreate,
  validateFilesPresent,
  validateUploadedBy,
} from '../middleware/validation';

function mockReq(body: Record<string, string>, file?: object, files?: object[]): Partial<Request> {
  return { body, file, files } as unknown as Partial<Request>;
}

function mockRes() {
  const res: Partial<Response> = {};
  res.status = jest.fn().mockReturnValue(res);
  res.json = jest.fn().mockReturnValue(res);
  return res as Response;
}

const next: NextFunction = jest.fn();

beforeEach(() => {
  (next as jest.Mock).mockClear();
});

describe('validateGuestCreate', () => {
  const valid = { name: 'Alice', email: 'alice@example.com', phone: '+15550001111', preferredChannel: 'email' };

  it('passes with valid input', () => {
    const req = mockReq(valid);
    const res = mockRes();
    validateGuestCreate(req as Request, res, next);
    expect(next).toHaveBeenCalled();
    expect(res.status).not.toHaveBeenCalled();
  });

  it('rejects missing name', () => {
    const res = mockRes();
    validateGuestCreate(mockReq({ ...valid, name: '' }) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(next).not.toHaveBeenCalled();
  });

  it('rejects invalid email', () => {
    const res = mockRes();
    validateGuestCreate(mockReq({ ...valid, email: 'not-an-email' }) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it('rejects invalid preferredChannel', () => {
    const res = mockRes();
    validateGuestCreate(mockReq({ ...valid, preferredChannel: 'telegram' }) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it('rejects short phone number', () => {
    const res = mockRes();
    validateGuestCreate(mockReq({ ...valid, phone: '123' }) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });
});

describe('validateFilesPresent', () => {
  it('calls next when single file present', () => {
    const res = mockRes();
    validateFilesPresent(mockReq({}, { fieldname: 'photo' }) as Request, res, next);
    expect(next).toHaveBeenCalled();
  });

  it('calls next when multiple files present', () => {
    const res = mockRes();
    validateFilesPresent(mockReq({}, undefined, [{ fieldname: 'photos' }]) as Request, res, next);
    expect(next).toHaveBeenCalled();
  });

  it('rejects when no files', () => {
    const res = mockRes();
    validateFilesPresent(mockReq({}) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });
});

describe('validateUploadedBy', () => {
  it.each(['guest', 'photographer', 'admin'])('accepts %s', (uploadedBy) => {
    const res = mockRes();
    validateUploadedBy(mockReq({ uploadedBy }) as Request, res, next);
    expect(next).toHaveBeenCalled();
  });

  it('rejects unknown role', () => {
    const res = mockRes();
    validateUploadedBy(mockReq({ uploadedBy: 'stranger' }) as Request, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });
});
