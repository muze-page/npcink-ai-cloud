import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestOrigin,
  getExternalRequestHost,
  getExternalRequestProto,
  requireAdminCapability,
  requireAdminSessionData,
  type AdminCapability,
} from '../_shared';
import { getInternalAuthToken } from '@/lib/env';

/**
 * Admin API catch-all proxy.
 *
 * Only declared method/path pairs may receive the internal service token.
 * Adding an internal endpoint does not expose it through this browser proxy.
 */

type AdminMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

type AdminRouteRule = {
  methods: readonly AdminMethod[];
  pattern: RegExp;
  namespace: 'admin' | 'service';
  requiredCapability?: AdminCapability;
};

type AdminRouteResolution = {
  backendPath: string;
  requiredCapability?: AdminCapability;
};

const ADMIN_ROUTE_RULES: readonly AdminRouteRule[] = [
  // Operator and diagnostic reads.
  {
    methods: ['GET'],
    pattern: /^(?:overview|plugin-observability|media-observability|vector-observability|agent-feedback|runtime-telemetry|agent-workflow-metadata)$/,
    namespace: 'admin',
    requiredCapability: 'can_review_diagnostics',
  },
  {
    methods: ['GET'],
    pattern: /^audit-events(?:\/summary)?$/,
    namespace: 'service',
    requiredCapability: 'can_review_diagnostics',
  },

  // Customer and support reads.
  {
    methods: ['GET'],
    pattern: /^(?:accounts|portal-users|sites|support-requests)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['GET'],
    pattern: /^accounts\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['GET'],
    pattern: /^accounts\/[^/]+\/quota-summary$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['GET'],
    pattern: /^portal-users\/[^/]+\/audit$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['GET'],
    pattern: /^sites\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['GET'],
    pattern: /^support-requests\/[^/]+(?:\/attachments\/[^/]+)?$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },

  // Commercial and catalog reads.
  {
    methods: ['GET'],
    pattern: /^(?:coverage-work-queue|subscriptions)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['GET'],
    pattern: /^accounts\/[^/]+\/(?:credit-ledger|subscription)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['GET'],
    pattern: /^subscriptions\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['GET'],
    pattern: /^(?:plans|credit-packs)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['GET'],
    pattern: /^plans\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },

  // Cloud runtime configuration reads.
  {
    methods: ['GET'],
    pattern: /^(?:ai-resources|provider-connections|model-references|site-knowledge-vector-profile|runtime-profiles)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['GET'],
    pattern: /^provider-connections\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['GET'],
    pattern: /^service-settings$/,
    namespace: 'admin',
    // The existing session model has no service-settings capability.
    // The platform_admin identity/role gate remains the explicit authority.
  },

  // Customer, commercial, and catalog writes.
  {
    methods: ['POST'],
    pattern: /^accounts$/,
    namespace: 'service',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['POST'],
    pattern: /^sites\/[^/]+\/activate$/,
    namespace: 'service',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['POST'],
    pattern: /^accounts\/[^/]+\/(?:suspend|restore|agency-quotes|agency-trial)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['POST'],
    pattern: /^portal-users\/(?:batch-disable|[^/]+\/disable)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['PATCH'],
    pattern: /^support-requests\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['POST'],
    pattern: /^support-requests\/[^/]+\/(?:messages|attachments)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_accounts',
  },
  {
    methods: ['POST'],
    pattern: /^accounts\/[^/]+\/subscription(?:\/(?:suspend|cancel))?$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['POST'],
    pattern: /^accounts\/[^/]+\/credit-ledger\/adjustments$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['POST'],
    pattern: /^subscriptions\/[^/]+\/billing-snapshots\/rebuild$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['POST'],
    pattern: /^subscriptions\/[^/]+\/topup$/,
    namespace: 'service',
    requiredCapability: 'can_manage_billing',
  },
  {
    methods: ['POST'],
    pattern: /^plans(?:\/[^/]+\/versions)?$/,
    namespace: 'service',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['PATCH'],
    pattern: /^credit-packs$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },

  // Cloud runtime configuration and bounded diagnostic writes.
  {
    methods: ['POST'],
    pattern: /^plugin-observability\/attention-state$/,
    namespace: 'admin',
    requiredCapability: 'can_review_diagnostics',
  },
  {
    methods: ['POST'],
    pattern: /^(?:provider-connections|provider-connections\/preview-catalog|model-references\/sync)$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['POST'],
    pattern: /^provider-connections\/[^/]+\/test$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['PATCH', 'DELETE'],
    pattern: /^provider-connections\/[^/]+$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['PUT'],
    pattern: /^site-knowledge-vector-profile(?:\/vector-store)?$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['PUT'],
    pattern: /^runtime-profiles$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['POST'],
    pattern: /^site-knowledge-vector-profile\/index-rebuilds$/,
    namespace: 'admin',
    requiredCapability: 'can_manage_catalog',
  },
  {
    methods: ['PATCH'],
    pattern: /^service-settings\/(?:portal-public|qq-login|email|alipay-payment)$/,
    namespace: 'admin',
  },
  {
    methods: ['POST'],
    pattern: /^service-settings\/(?:qq-login\/test|email\/test|email\/preview|alipay-payment\/test)$/,
    namespace: 'admin',
  },
];

const ADMIN_IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

function createAdminIdempotencyKey(): string {
  const random =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '')
      : Math.random().toString(36).slice(2);
  return `admin_write_${Date.now()}_${random}`.slice(0, 128);
}

function resolveAdminIdempotencyKey(request: NextRequest): string {
  const requested = String(request.headers.get('idempotency-key') || '').trim();
  if (ADMIN_IDEMPOTENCY_KEY_PATTERN.test(requested)) {
    return requested;
  }
  return createAdminIdempotencyKey();
}

function resolveAdminRoute(
  pathSegments: string[],
  method: string
): AdminRouteResolution | null {
  const normalized = pathSegments
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join('/');

  const upperMethod = method.toUpperCase() as AdminMethod;
  const rule = ADMIN_ROUTE_RULES.find(
    (candidate) =>
      candidate.methods.includes(upperMethod) && candidate.pattern.test(normalized)
  );
  if (!rule) {
    return null;
  }
  const prefix =
    rule.namespace === 'admin' ? '/internal/service/admin' : '/internal/service';
  return {
    backendPath: `${prefix}/${normalized}`,
    requiredCapability: rule.requiredCapability,
  };
}

async function proxyAdminRequest(
  request: NextRequest,
  pathSegments: string[],
  options: {
    method?: string;
    unreachableCode: string;
    unreachableMessage: string;
  }
): Promise<NextResponse> {
  const method = (options.method || request.method).toUpperCase();
  const routeResolution = resolveAdminRoute(pathSegments, method);
  const accept = request.headers.get('accept');
  const contentType = request.headers.get('content-type');
  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');

  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }
  if (!routeResolution) {
    return buildErrorResponse(
      404,
      'proxy.admin_route_not_allowed',
      'admin route is not exposed'
    );
  }
  if (routeResolution.requiredCapability) {
    const capabilityError = requireAdminCapability(
      sessionResult.session,
      routeResolution.requiredCapability
    );
    if (capabilityError) {
      return capabilityError;
    }
  }

  const headers = buildForwardedRequestHeaders(request, {
    Accept: accept || 'application/json',
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';

  const acceptLanguage = request.headers.get('accept-language');
  if (acceptLanguage) {
    headers['accept-language'] = acceptLanguage;
  }

  // Add internal token for all admin requests
  headers['X-Npcink-Internal-Token'] = getInternalAuthToken();

  // Add idempotency key for write requests
  if (method !== 'GET' && method !== 'HEAD') {
    headers['Idempotency-Key'] = resolveAdminIdempotencyKey(request);
  }

  let body: string | undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    body = await request.text();
    if (!body) {
      body = undefined;
    }
    if (contentType) {
      headers['Content-Type'] = contentType;
    }
  }

  let response: Response;
  try {
    response = await fetch(buildBackendUrl(routeResolution.backendPath, request.nextUrl.search), {
      method,
      headers,
      body,
      cache: 'no-store',
    });
  } catch {
    return buildErrorResponse(
      502,
      options.unreachableCode,
      options.unreachableMessage
    );
  }

  return forwardBackendJson(response);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_get_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_post_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_put_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_patch_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_delete_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}
