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

// Envelope
export {
  unwrapEnvelope,
  isErrorEnvelope,
  CloudApiError,
  getErrorMessage,
  type CloudEnvelope,
} from './envelope';

// Cloud Client
export {
  CloudClient,
  createCloudClient,
  getDefaultClient,
  type CloudClientConfig,
} from './cloud-client';

// Idempotency
export {
  generateIdempotencyKey,
  isValidIdempotencyKey,
  IdempotencyKeys,
} from './idempotency';

// Errors
export {
  SessionError,
  SiteSelectionError,
  ApiError,
  NetworkError,
  ValidationError,
  createErrorFromCode,
  getErrorMessageFromError,
  requiresLogin,
  requiresSiteSelection,
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
  PortalApiError,
  type PortalSession,
  type Site,
  type ApiKey,
  type ApiKeyWithSecret,
  type RotateKeyResponse,
  type PortalLoginCodeRequest,
  type PortalLoginCodeVerifyRequest,
  type PortalRegistrationCodeRequest,
  type PortalRegistrationVerifyRequest,
  type PortalRegistrationResult,
  type PortalIdentityProviderBinding,
  type PortalIdentityProviderStatus,
  type PortalIdentityProvidersResponse,
  type PortalQqStartResponse,
  type CreateKeyRequest,
  type RotateKeyRequest,
} from './portal-client';
