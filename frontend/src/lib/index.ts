/**
 * Library exports
 */

// Components
export {
  ToastProvider,
  useToast,
  type Toast,
  type ToastType,
} from '@/components/ui/Toast';

export {
  Skeleton,
  SkeletonCard,
  SkeletonList,
  SkeletonTable,
} from '@/components/ui/Skeleton';

export {
  EmptyState,
  EmptyStates,
  type EmptyStateProps,
} from '@/components/ui/EmptyState';

// Hooks
export {
  useRetry,
  useSimpleRetry,
  useFetchRetry,
  type RetryOptions,
  type RetryResult,
  type FetchRetryOptions,
} from '@/hooks/useRetry';

// Environment
export { getEnv, getApiBaseUrl, getPublicBaseUrl, validateEnv } from './env';

// API Client and Error Contract
export {
  ApiClient,
  createApiClient,
  requestApi,
  type ApiClientConfig,
  type ApiEnvelope,
  type ApiEnvelopeMeta,
  type ApiMethod,
  type ApiRequestOptions,
} from './api-client';

// Idempotency
export {
  generateIdempotencyKey,
  isValidIdempotencyKey,
  IdempotencyKeys,
} from './idempotency';

// Errors
export {
  ApiError,
  resolveUiErrorMessage,
  type ApiErrorInit,
} from './errors';

// Utils
export {
  cn,
  formatDate,
  formatRelativeTime,
  truncate,
  maskSensitive,
  parseScopes,
  generateId,
} from './utils';

// Portal Client
export {
  portalClient,
  PortalClient,
  type PortalSession,
  type Site,
  type PortalLoginCodeRequest,
  type PortalLoginCodeVerifyRequest,
  type PortalRegistrationCodeRequest,
  type PortalRegistrationVerifyRequest,
  type PortalRegistrationResult,
  type PortalIdentityProviderBinding,
  type PortalIdentityProviderStatus,
  type PortalIdentityProvidersResponse,
  type PortalQqStartResponse,
} from './portal-client';
