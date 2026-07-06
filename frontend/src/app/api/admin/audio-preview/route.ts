import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  requireAdminSessionData,
} from '../_shared';

const ALLOWED_MINIMAX_AUDIO_HOSTS = new Set([
  'minimax-algeng-chat-tts.oss-cn-wulanchabu.aliyuncs.com',
]);

type ParsedAudioUrl = {
  url: URL;
  source: 'cloud_artifact' | 'external';
};

function parseAudioUrl(request: NextRequest): ParsedAudioUrl | null {
  const rawUrl = request.nextUrl.searchParams.get('url') || '';
  if (!rawUrl) {
    return null;
  }
  try {
    if (rawUrl.startsWith('/')) {
      return {
        url: new URL(rawUrl, 'http://cloud-runtime.local'),
        source: 'cloud_artifact',
      };
    }
    return {
      url: new URL(rawUrl),
      source: 'external',
    };
  } catch {
    return null;
  }
}

function isAllowedCloudArtifactUrl(url: URL): boolean {
  return (
    url.pathname.match(/^\/v1\/runtime\/artifacts\/art_[A-Za-z0-9]+\/public-download$/) !== null &&
    Boolean(url.searchParams.get('token')) &&
    Array.from(url.searchParams.keys()).every((key) => key === 'token')
  );
}

function isAllowedExternalAudioUrl(url: URL): boolean {
  return url.protocol === 'https:' && ALLOWED_MINIMAX_AUDIO_HOSTS.has(url.hostname);
}

function isAllowedAudioUrl(parsed: ParsedAudioUrl): boolean {
  if (parsed.source === 'cloud_artifact') {
    return isAllowedCloudArtifactUrl(parsed.url);
  }
  return isAllowedExternalAudioUrl(parsed.url);
}

function audioFetchUrl(parsed: ParsedAudioUrl): string | URL {
  if (parsed.source === 'cloud_artifact') {
    return buildBackendUrl(`${parsed.url.pathname}${parsed.url.search}`);
  }
  return parsed.url;
}

function copyAudioResponseHeaders(source: Response): Headers {
  const headers = new Headers();
  for (const header of [
    'accept-ranges',
    'content-length',
    'content-range',
    'content-type',
    'etag',
    'last-modified',
  ]) {
    const value = source.headers.get(header);
    if (value) {
      headers.set(header, value);
    }
  }
  if (!headers.has('content-type')) {
    headers.set('content-type', 'audio/mpeg');
  }
  headers.set('cache-control', 'no-store');
  headers.set('x-content-type-options', 'nosniff');
  return headers;
}

async function proxyAudioPreview(request: NextRequest, method: 'GET' | 'HEAD'): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }

  const audioUrl = parseAudioUrl(request);
  if (!audioUrl || !isAllowedAudioUrl(audioUrl)) {
    return buildErrorResponse(
      400,
      'audio_preview.url_not_allowed',
      'audio preview URL is not allowed'
    );
  }

  const range = request.headers.get('range');
  const headers: Record<string, string> = {
    Accept: 'audio/*,*/*;q=0.8',
  };
  if (range) {
    headers.Range = range;
  } else if (method === 'HEAD') {
    headers.Range = 'bytes=0-0';
  }

  let response: Response;
  try {
    response = await fetch(audioFetchUrl(audioUrl), {
      method: 'GET',
      headers,
      cache: 'no-store',
      redirect: 'follow',
    });
  } catch (error) {
    return buildErrorResponse(
      502,
      'audio_preview.source_unreachable',
      error instanceof Error ? error.message : 'failed to reach audio source'
    );
  }

  if (!response.ok && response.status !== 206) {
    return buildErrorResponse(
      502,
      'audio_preview.source_rejected',
      'audio source rejected the preview request'
    );
  }

  return new NextResponse(method === 'HEAD' ? null : response.body, {
    status: response.status,
    headers: copyAudioResponseHeaders(response),
  });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  return proxyAudioPreview(request, 'GET');
}

export async function HEAD(request: NextRequest): Promise<NextResponse> {
  return proxyAudioPreview(request, 'HEAD');
}
