import dotenv from 'dotenv';
import path from 'path';

// Load the worker's own .env, then fall back to the backend's .env so a single
// source of truth still works during local development.
dotenv.config();
dotenv.config({ path: path.resolve(__dirname, '../../backend/.env') });

function required(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Missing required env var: ${key}`);
  return value;
}

function optional(key: string, fallback: string): string {
  return process.env[key] ?? fallback;
}

export const config = {
  solace: {
    host: required('SOLACE_HOST'),
    vpnName: required('SOLACE_VPN_NAME'),
    username: required('SOLACE_USERNAME'),
    password: required('SOLACE_PASSWORD'),
    queue: required('EMAIL_SOLACE_QUEUE'),
  },

  email: {
    host: optional('EMAIL_HOST', 'smtp.gmail.com'),
    port: parseInt(optional('EMAIL_PORT', '587'), 10),
    user: required('EMAIL_USER'),
    pass: required('EMAIL_PASS'),
    from: optional('EMAIL_FROM', 'wedding@example.com'),
  },
};
