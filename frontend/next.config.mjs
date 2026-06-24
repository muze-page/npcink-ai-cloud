import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, '..');

const defaultMiniDevOrigins = ['127.0.0.1', 'localhost', '0.0.0.0'];

function parseMiniDevOrigins(rawValue) {
  const raw = String(rawValue || '').trim();
  if (!raw) {
    return defaultMiniDevOrigins;
  }

  const values = raw
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  const normalized = values.flatMap((value) => {
    try {
      return [new URL(value).hostname.trim().toLowerCase()];
    } catch {
      return [value.split(':')[0]?.trim().toLowerCase() || ''];
    }
  });

  return normalized.filter(Boolean).length > 0 ? [...new Set(normalized.filter(Boolean))] : defaultMiniDevOrigins;
}

const miniDevOrigins = parseMiniDevOrigins(process.env.NPCINK_CLOUD_FRONTEND_DEV_HOST_ALLOWLIST);

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  allowedDevOrigins: miniDevOrigins,
  turbopack: {
    root: workspaceRoot,
  },
  env: {
    NEXT_PUBLIC_MINI_DEV_HOST_ALLOWLIST: miniDevOrigins.join(','),
  },
};

export default nextConfig;
