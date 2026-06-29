import { z } from 'zod';

/**
 * Frontend environment schema
 * Validated on server-side only - never expose these to client components
 */
const envSchema = z.object({
  CLOUD_API_BASE_URL: z.string().url().default('http://127.0.0.1:8000'),
  CLOUD_PUBLIC_BASE_URL: z.string().url().default('http://127.0.0.1:8010'),
  NPCINK_CLOUD_INTERNAL_AUTH_TOKEN: z.string().optional().default(''),
  NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN: z.string().optional().default(''),
  NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID: z.string().optional().default('platform:internal_root'),
  NPCINK_CLOUD_DEV_PORTAL_EMAIL: z.string().optional().default('portal-demo@example.com'),
  NPCINK_CLOUD_DEV_PORTAL_SITE_ID: z.string().optional().default('site_smoke'),
});

export type Env = z.infer<typeof envSchema>;

let cachedEnv: Env | undefined;

const DEFAULT_MINI_DEV_HOST_ALLOWLIST = ['127.0.0.1', 'localhost', '0.0.0.0'] as const;
const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';
const DEFAULT_PUBLIC_BASE_URL = 'http://127.0.0.1:8010';
const NON_DEVELOPMENT_ENVS = new Set(['production', 'staging']);

function getRuntimeEnvironment(): string {
  const explicitEnv = String(process.env.NEXT_PUBLIC_ENV || '').trim().toLowerCase();
  if (explicitEnv) {
    return explicitEnv;
  }

  return String(process.env.NODE_ENV || 'development').trim().toLowerCase();
}

function isNonDevelopmentEnvironment(): boolean {
  return NON_DEVELOPMENT_ENVS.has(getRuntimeEnvironment());
}

function isLoopbackUrl(url: string): boolean {
  try {
    const hostname = new URL(url).hostname.trim().toLowerCase();
    return DEFAULT_MINI_DEV_HOST_ALLOWLIST.includes(
      hostname as (typeof DEFAULT_MINI_DEV_HOST_ALLOWLIST)[number]
    );
  } catch {
    return false;
  }
}

function parseMiniDevHostAllowlist(rawValue: string | undefined): string[] {
  const raw = String(rawValue || '').trim();

  if (!raw) {
    return [...DEFAULT_MINI_DEV_HOST_ALLOWLIST];
  }

  const hosts = raw
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .map((value) => {
      try {
        return new URL(value).hostname.trim().toLowerCase();
      } catch {
        return value;
      }
    })
    .filter(Boolean);

  return hosts.length > 0 ? Array.from(new Set(hosts)) : [...DEFAULT_MINI_DEV_HOST_ALLOWLIST];
}

function getMiniDevHostAllowlist(): string[] {
  return parseMiniDevHostAllowlist(process.env.NEXT_PUBLIC_MINI_DEV_HOST_ALLOWLIST);
}

/**
 * Parse and validate environment variables
 * @throws {Error} If validation fails
 */
export function validateEnv(): Env {
  if (cachedEnv) {
    return cachedEnv;
  }

  const runtimeEnvironment = getRuntimeEnvironment();
  const rawApiBaseUrl = process.env.CLOUD_API_BASE_URL;
  const rawPublicBaseUrl = process.env.CLOUD_PUBLIC_BASE_URL;
  const result = envSchema.safeParse({
    CLOUD_API_BASE_URL: rawApiBaseUrl,
    CLOUD_PUBLIC_BASE_URL: rawPublicBaseUrl,
    NPCINK_CLOUD_INTERNAL_AUTH_TOKEN: process.env.NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,
    NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN: process.env.NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN,
    NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID: process.env.NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID,
    NPCINK_CLOUD_DEV_PORTAL_EMAIL: process.env.NPCINK_CLOUD_DEV_PORTAL_EMAIL,
    NPCINK_CLOUD_DEV_PORTAL_SITE_ID: process.env.NPCINK_CLOUD_DEV_PORTAL_SITE_ID,
  });

  if (!result.success) {
    throw new Error(
      `Invalid environment configuration: ${result.error.message}`
    );
  }

  if (isNonDevelopmentEnvironment()) {
    const missingVars: string[] = [];
    if (!rawApiBaseUrl) {
      missingVars.push('CLOUD_API_BASE_URL');
    }
    if (!rawPublicBaseUrl) {
      missingVars.push('CLOUD_PUBLIC_BASE_URL');
    }
    if (missingVars.length > 0) {
      throw new Error(
        `Missing required environment configuration for ${runtimeEnvironment}: ${missingVars.join(', ')}`
      );
    }

    if (
      result.data.CLOUD_API_BASE_URL === DEFAULT_API_BASE_URL ||
      result.data.CLOUD_PUBLIC_BASE_URL === DEFAULT_PUBLIC_BASE_URL ||
      isLoopbackUrl(result.data.CLOUD_API_BASE_URL) ||
      isLoopbackUrl(result.data.CLOUD_PUBLIC_BASE_URL)
    ) {
      throw new Error(
        `Loopback Cloud frontend URLs are not allowed in ${runtimeEnvironment}; configure real CLOUD_API_BASE_URL and CLOUD_PUBLIC_BASE_URL`
      );
    }
  }

  cachedEnv = result.data;
  return cachedEnv;
}

/**
 * Get validated environment variables
 * @returns {Env} Validated environment
 */
export function getEnv(): Env {
  return validateEnv();
}

/**
 * Get API base URL
 */
export function getApiBaseUrl(): string {
  return getEnv().CLOUD_API_BASE_URL;
}

function joinUrl(base: string, pathname: string): string {
  const trimmedBase = base.replace(/\/$/, '');
  const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
  return `${trimmedBase}${normalizedPath}`;
}

function isBrowserRuntime(): boolean {
  return typeof window !== 'undefined';
}

export function isMiniDevHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return getMiniDevHostAllowlist().includes(host);
}

export function isMiniDevRequestHost(hostHeader: string | null | undefined): boolean {
  const value = String(hostHeader || '').trim().toLowerCase();
  if (!value) {
    return false;
  }
  const hostname = value.split(',')[0]?.trim().split(':')[0]?.trim() || '';
  return isMiniDevHost(hostname);
}

export function getPortalApiBaseUrl(): string {
  if (isBrowserRuntime()) {
    return '/api/portal';
  }

  return joinUrl(getApiBaseUrl(), '/portal/v1');
}

export function getRuntimeApiBaseUrl(): string {
  if (isBrowserRuntime()) {
    return '/v1';
  }

  return joinUrl(getApiBaseUrl(), '/v1');
}

/**
 * Get public base URL
 */
export function getPublicBaseUrl(): string {
  return getEnv().CLOUD_PUBLIC_BASE_URL;
}

export function getInternalAuthToken(): string {
  const token = getEnv().NPCINK_CLOUD_INTERNAL_AUTH_TOKEN.trim();

  if (!token) {
    throw new Error('NPCINK_CLOUD_INTERNAL_AUTH_TOKEN is not configured for frontend admin proxy');
  }

  return token;
}

export function getAdminBootstrapToken(): string {
  const token = getEnv().NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN.trim();

  if (!token) {
    throw new Error('NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN is not configured for frontend admin bootstrap');
  }

  return token;
}

export function getAdminBootstrapAdminRef(): string {
  return getEnv().NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID.trim() || 'platform:internal_root';
}

export function getDevPortalEmail(): string {
  return getEnv().NPCINK_CLOUD_DEV_PORTAL_EMAIL.trim().toLowerCase() || 'portal-demo@example.com';
}

export function getDevPortalSiteId(): string {
  return getEnv().NPCINK_CLOUD_DEV_PORTAL_SITE_ID.trim() || 'site_smoke';
}
