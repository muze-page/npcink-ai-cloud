'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AdminSemanticBadge, HostedMetadataBadges } from '@/components/admin/HostedMetadataBadges';
import { ReviewStatusBadge, translateReviewStatus } from '@/components/admin/ReviewStatusBadge';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type RecognitionAnnotation = {
  review_status: string;
  manual_tags: string[];
  operator_notes: string;
  recommended: boolean;
  cost_tier_override: string;
  visibility: string;
  badges: string[];
  updated_at: string;
};

type RecognitionListItem = {
  provider_id: string;
  model_id: string;
  model_type: string;
  preview_type: string;
  confidence: number;
  price_input: number | null;
  price_output: number | null;
  price_source: string;
  price_updated_at: string;
  price_confidence: number;
  has_price_conflict: boolean;
  source: string;
  source_coverage_count: number;
  source_coverage_sources: string[];
  aliases: string[];
  short_description: string;
  best_for: string;
  supports: string[];
  price_summary: string;
  evidence_sources: string[];
  primary_evidence: { source: string; confidence: number } | null;
  evidence_source_count: number;
  updated_at: string;
  in_hosted_catalog: boolean;
  has_match_conflict: boolean;
  has_capability_conflict: boolean;
  is_new_since_previous_snapshot: boolean;
  match_conflict_keys: string[];
  why_not_in_hosted_catalog: string;
  annotation: RecognitionAnnotation;
};

type RecognitionDetail = RecognitionListItem & {
  match_keys: string[];
  input_modalities: string[];
  output_modalities: string[];
  capabilities: Record<string, boolean>;
  evidence: Array<{ source: string; confidence: number }>;
  primary_evidence: { source: string; confidence: number } | null;
  secondary_evidence: Array<{ source: string; confidence: number }>;
  price_sources: Array<{
    source: string;
    price_source: string;
    price_input: number | null;
    price_output: number | null;
    price_updated_at: string;
    price_confidence: number;
  }>;
  capability_sources: Array<{
    source: string;
    model_type: string;
    preview_type: string;
    capabilities: Record<string, boolean>;
    confidence: number;
  }>;
  evidence_source_count: number;
  hosted_catalog: {
    provider_id: string;
    model_id: string;
    feature: string;
    status: string;
  };
  hosted_metadata: {
    recommended: boolean;
    cost_tier: string;
    visibility: string;
    badges: string[];
    updated_at: string;
  };
  recognition_bundle: {
    revision: string;
    checksum: string;
    published_at: string;
  };
  pricing: PricingConfig;
};

type PricingConfig = {
  base_currency: 'USD';
  supported_currencies: Array<'USD' | 'CNY'>;
  cny_per_usd: number;
  unit: string;
};

type RecognitionResponse = {
  items: RecognitionListItem[];
  total: number;
  pagination: {
    page: number;
    per_page: number;
    pages_total: number;
    offset: number;
  };
  sort: {
    sort_by: string;
    sort_dir: string;
  };
  summary: {
    hosted_catalog_total: number;
    not_in_hosted_catalog_total: number;
    candidate_not_in_hosted_total: number;
    low_confidence_total: number;
    conflict_total: number;
    price_conflict_total: number;
    capability_conflict_total: number;
    new_models_total: number;
    disappeared_models_total: number;
    disappeared_models: Array<{ provider_id: string; model_id: string }>;
    review_status_counts: Record<string, number>;
    sources: string[];
    source_counts: Record<string, number>;
    source_trends: Array<{
      source: string;
      current_total: number;
      previous_total: number;
      delta: number;
      previous_revision: string;
    }>;
    source_runs: Array<{
      source_key?: string;
      source?: string;
      run_id?: string;
      records_total?: number;
      records_fetched?: number;
      records_accepted?: number;
      status: string;
      generated_at: string;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      error?: string;
    }>;
    manual_tag_suggestions: string[];
  };
  pricing: PricingConfig;
  recognition_bundle: {
    revision: string;
    checksum: string;
    published_at: string;
    snapshot_delta?: {
      new_models_total: number;
      disappeared_models_total: number;
      previous_revision: string;
    };
    admin_source?: {
      kind: string;
      configured: boolean;
      snapshot_exists: boolean;
      records_total: number;
      generated_at: string;
      hours_old?: number | null;
      freshness_status?: string;
      source_keys?: string[];
      failed_sources?: string[];
      health_status?: string;
      health_issues?: string[];
      operator_alerts?: Array<{
        code: string;
        severity: string;
        hours_old?: number | null;
        failed_sources?: string[];
        cached_sources_used?: string[];
        bundle_retained_reason?: string;
      }>;
      bundle_exists?: boolean;
      fallback?: {
        previous_bundle_used?: boolean;
        published_bundle_source?: string;
        bundle_retained_reason?: string;
        cached_sources_used?: string[];
      };
      latest_publication?: {
        revision?: string;
        checksum?: string;
        generated_at?: string;
        hours_old?: number | null;
        freshness_status?: string;
      };
      recent_publications?: Array<{
        revision?: string;
        checksum?: string;
        generated_at?: string;
        hours_old?: number | null;
        freshness_status?: string;
        records_total?: number;
        source_keys?: string[];
        failed_sources?: string[];
        fallback?: {
          previous_bundle_used?: boolean;
          bundle_retained_reason?: string;
          cached_sources_used?: string[];
        };
      }>;
    };
  };
};

type FilterState = {
  search: string;
  provider_id: string;
  review_status: string;
  in_hosted_catalog: string;
  source: string;
  quick_filter: string;
  page: number;
  per_page: number;
  sort_by: string;
  sort_dir: string;
  model_id: string;
};

type LoadIssueKind = 'auth' | 'failed' | null;
type PricingCurrency = 'USD' | 'CNY';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

function compactChecksum(value: string, fallback = 'n/a'): string {
  if (!value) {
    return fallback;
  }
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

function translateHealthStatus(value: string, t: TranslateFn): string {
  switch (value) {
    case 'ok':
      return t('common.ok', {}, 'OK');
    case 'warning':
      return t('common.warning', {}, 'Warning');
    default:
      return t('common.error', {}, 'Error');
  }
}

function toBackofficeHealthStatus(value: string): string {
  switch (value) {
    case 'ok':
      return 'active';
    case 'warning':
      return 'warning';
    default:
      return 'error';
  }
}

function translatePublisherIssue(value: string, t: TranslateFn): string {
  switch (value) {
    case 'publisher_disabled':
      return t('admin.publisher_issue_disabled', {}, 'Publisher is disabled');
    case 'publisher_unconfigured':
      return t('admin.publisher_issue_unconfigured', {}, 'Publisher paths are not configured');
    case 'bundle_missing':
      return t('admin.publisher_issue_bundle_missing', {}, 'No current bundle is available');
    case 'bundle_stale':
      return t('admin.publisher_issue_bundle_stale', {}, 'Bundle is older than the preferred freshness window');
    case 'bundle_expired':
      return t('admin.publisher_issue_bundle_expired', {}, 'Bundle is beyond the freshness SLA');
    case 'source_failures_present':
      return t('admin.publisher_issue_source_failures', {}, 'One or more publisher sources failed');
    case 'previous_bundle_fallback_used':
      return t('admin.publisher_issue_fallback_used', {}, 'Publisher retained a previous bundle as fallback');
    default:
      return value || t('common.not_available', {}, 'N/A');
  }
}

function translateFreshnessStatus(value: string, t: TranslateFn): string {
  switch (value) {
    case 'fresh':
      return t('admin.intelligence_freshness_fresh', {}, 'Fresh');
    case 'stale':
      return t('admin.intelligence_freshness_stale', {}, 'Stale');
    case 'expired':
      return t('admin.intelligence_freshness_expired', {}, 'Expired');
    default:
      return t('admin.intelligence_freshness_missing', {}, 'Missing');
  }
}

function toBackofficeFreshnessStatus(value: string): string {
  switch (value) {
    case 'fresh':
      return 'active';
    case 'stale':
      return 'warning';
    case 'expired':
      return 'error';
    default:
      return 'unknown';
  }
}

function translateRecognitionSourceKind(value: string, t: TranslateFn): string {
  switch (value) {
    case 'recognition_evidence_snapshot':
      return t('admin.recognition_source_kind_snapshot', {}, 'Live intelligence snapshot');
    case 'publisher_bundle':
      return t('admin.recognition_source_kind_publisher_bundle', {}, 'Publisher intelligence bundle');
    case 'unconfigured':
      return t('admin.recognition_source_kind_unconfigured', {}, 'No intelligence source configured');
    default:
      return value || t('common.not_available', {}, 'N/A');
  }
}

function translateRecognitionEvidenceSource(value: string, t: TranslateFn): string {
  switch (value) {
    case 'openrouter_model_info':
      return t('admin.recognition_source_openrouter', {}, 'OpenRouter');
    case 'huggingface_model_info':
      return t('admin.recognition_source_huggingface', {}, 'Hugging Face');
    case 'siliconflow_pricing_page':
      return t('admin.recognition_source_siliconflow', {}, 'SiliconFlow');
    case 'litellm_model_info':
      return t('admin.recognition_source_litellm', {}, 'LiteLLM');
    case 'ollama_catalog_show':
      return t('admin.recognition_source_ollama_catalog', {}, 'Ollama catalog');
    case 'ollama_show':
      return t('admin.recognition_source_ollama_node', {}, 'Ollama node');
    default:
      return value || t('common.not_available', {}, 'N/A');
  }
}

function translateOperatorAlertCode(
  value: string,
  t: TranslateFn,
  alert?: {
    hours_old?: number | null;
    failed_sources?: string[];
    cached_sources_used?: string[];
    bundle_retained_reason?: string;
  }
): string {
  switch (value) {
    case 'publisher_unconfigured':
      return t(
        'admin.publisher_alert_unconfigured',
        {},
        'Publisher paths are not configured in this environment.'
      );
    case 'bundle_expired':
      return alert?.hours_old != null
        ? t(
            'admin.publisher_alert_expired',
            { hours: String(alert.hours_old) },
            `Current bundle is expired (${alert.hours_old}h old).`
          )
        : t('admin.publisher_alert_expired_plain', {}, 'Current bundle is expired.');
    case 'bundle_stale':
      return alert?.hours_old != null
        ? t(
            'admin.publisher_alert_stale',
            { hours: String(alert.hours_old) },
            `Current bundle is stale (${alert.hours_old}h old).`
          )
        : t('admin.publisher_alert_stale_plain', {}, 'Current bundle is stale.');
    case 'source_failures_present':
      return alert?.failed_sources?.length
        ? `${t('admin.publisher_alert_source_failures', {}, 'Latest run failed for')}: ${alert.failed_sources.join(', ')}`
        : t('admin.publisher_alert_source_failures_plain', {}, 'Latest run includes failed sources.');
    case 'previous_bundle_fallback_used':
      return alert?.bundle_retained_reason
        ? `${t('admin.publisher_alert_previous_bundle', {}, 'Latest refresh retained the previous bundle')}: ${alert.bundle_retained_reason}`
        : t('admin.publisher_alert_previous_bundle_plain', {}, 'Latest refresh retained the previous bundle.');
    case 'cached_sources_fallback_used':
      return alert?.cached_sources_used?.length
        ? `${t('admin.publisher_alert_cached_sources', {}, 'Cached source fallback used for')}: ${alert.cached_sources_used.join(', ')}`
        : t('admin.publisher_alert_cached_sources_plain', {}, 'Cached source fallback was used.');
    default:
      return value || t('common.not_available', {}, 'N/A');
  }
}

function toBackofficeAlertStatus(value: string): string {
  switch (value) {
    case 'error':
      return 'error';
    case 'warning':
      return 'warning';
    default:
      return 'active';
  }
}

function formatRecognitionPrice(
  amount: number | null | undefined,
  {
    currency,
    pricing,
  }: {
    currency: PricingCurrency;
    pricing: PricingConfig | null;
  },
): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) {
    return 'N/A';
  }
  const cnyPerUsd = pricing?.cny_per_usd || 7.2;
  const converted = currency === 'CNY' ? amount * cnyPerUsd : amount;
  const fractionDigits = converted >= 100 ? 2 : converted >= 1 ? 3 : 4;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(converted);
}

function formatRecognitionPriceSummary(
  item: { price_input: number | null; price_output: number | null },
  {
    currency,
    pricing,
    t,
  }: {
    currency: PricingCurrency;
    pricing: PricingConfig | null;
    t: TranslateFn;
  },
): string {
  const input = formatRecognitionPrice(item.price_input, { currency, pricing });
  const output = formatRecognitionPrice(item.price_output, { currency, pricing });
  if (input === 'N/A' && output === 'N/A') {
    return t('admin.price_not_available', {}, 'Price not available');
  }
  return `${t('admin.price_input', {}, 'Input')} ${input} · ${t('admin.price_output', {}, 'Output')} ${output}`;
}

function translateWhyNotInHostedCatalog(value: string, t: TranslateFn): string {
  switch (value) {
    case 'match_conflict':
      return t('admin.why_not_in_hosted_match_conflict', {}, 'Match conflict');
    case 'suppressed':
      return t('admin.why_not_in_hosted_suppressed', {}, 'Suppressed');
    case 'not_reviewed':
      return t('admin.why_not_in_hosted_not_reviewed', {}, 'Not reviewed');
    case 'low_confidence':
      return t('admin.why_not_in_hosted_low_confidence', {}, 'Low confidence');
    case 'not_marked_candidate':
      return t('admin.why_not_in_hosted_not_candidate', {}, 'Not marked as candidate');
    case 'not_curated_into_hosted_catalog':
      return t('admin.why_not_in_hosted_not_curated', {}, 'Not curated into hosted catalog');
    default:
      return t('admin.in_hosted_catalog_short', {}, 'Hosted');
  }
}

function getHostedModelsHref(providerId: string, modelId: string): string {
  return `/admin/models?provider_id=${encodeURIComponent(providerId)}&model_id=${encodeURIComponent(modelId)}`;
}

const DEFAULT_ADMIN_PAGE_SIZE = 10;

function isHostedCurationReady(model: RecognitionListItem | RecognitionDetail | null): boolean {
  if (!model) {
    return false;
  }
  return (
    !model.in_hosted_catalog &&
    !model.has_match_conflict &&
    model.annotation.review_status === 'candidate' &&
    model.why_not_in_hosted_catalog === 'not_curated_into_hosted_catalog'
  );
}

function readInitialFilters(searchParams: ReturnType<typeof useSearchParams>): FilterState {
  const page = Number.parseInt(searchParams.get('page') || '1', 10);
  const perPage = Number.parseInt(searchParams.get('per_page') || String(DEFAULT_ADMIN_PAGE_SIZE), 10);
  return {
    search: searchParams.get('search') || '',
    provider_id: searchParams.get('provider_id') || '',
    review_status: searchParams.get('review_status') || '',
    in_hosted_catalog: searchParams.get('in_hosted_catalog') || '',
    source: searchParams.get('source') || '',
    quick_filter: searchParams.get('quick_filter') || '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    per_page: Number.isFinite(perPage) && perPage > 0 ? perPage : DEFAULT_ADMIN_PAGE_SIZE,
    sort_by: searchParams.get('sort_by') || 'provider_id',
    sort_dir: searchParams.get('sort_dir') || 'asc',
    model_id: searchParams.get('model_id') || '',
  };
}

function RecognitionPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const notAvailableLabel = t('common.not_available', {}, 'N/A');
  const quickFilters = [
    { value: '', label: t('admin.quick_filter_all', {}, 'All rows'), tone: 'neutral' as const },
    {
      value: 'candidate_not_in_hosted',
      label: t('admin.quick_filter_candidate_not_in_hosted', {}, 'Candidate, not in hosted'),
      tone: 'info' as const,
    },
    {
      value: 'not_in_hosted_catalog',
      label: t('admin.quick_filter_not_in_hosted', {}, 'Not in hosted catalog'),
      tone: 'neutral' as const,
    },
    {
      value: 'low_confidence',
      label: t('admin.quick_filter_low_confidence', {}, 'Low confidence'),
      tone: 'warning' as const,
    },
    {
      value: 'conflicts',
      label: t('admin.quick_filter_conflicts', {}, 'Conflicts'),
      tone: 'danger' as const,
    },
    {
      value: 'capability_conflicts',
      label: t('admin.quick_filter_capability_conflicts', {}, 'Capability conflicts'),
      tone: 'warning' as const,
    },
    {
      value: 'price_conflicts',
      label: t('admin.quick_filter_price_conflicts', {}, 'Price conflicts'),
      tone: 'warning' as const,
    },
    {
      value: 'new_models',
      label: t('admin.quick_filter_new_models', {}, 'New models'),
      tone: 'success' as const,
    },
  ];

  const [filters, setFilters] = useState<FilterState>(() => readInitialFilters(searchParams));
  const [models, setModels] = useState<RecognitionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState<RecognitionResponse['pagination']>({
    page: 1,
    per_page: DEFAULT_ADMIN_PAGE_SIZE,
    pages_total: 1,
    offset: 0,
  });
  const [sortState, setSortState] = useState<RecognitionResponse['sort']>({
    sort_by: 'provider_id',
    sort_dir: 'asc',
  });
  const [summary, setSummary] = useState<RecognitionResponse['summary']>({
    hosted_catalog_total: 0,
    not_in_hosted_catalog_total: 0,
    candidate_not_in_hosted_total: 0,
    low_confidence_total: 0,
    conflict_total: 0,
    price_conflict_total: 0,
    capability_conflict_total: 0,
    new_models_total: 0,
    disappeared_models_total: 0,
    disappeared_models: [],
    review_status_counts: {},
    sources: [],
    source_counts: {},
    source_trends: [],
    source_runs: [],
    manual_tag_suggestions: [],
  });
  const [pricingConfig, setPricingConfig] = useState<PricingConfig | null>(null);
  const pricingCurrency: PricingCurrency = 'CNY';
  const [bundle, setBundle] = useState<RecognitionResponse['recognition_bundle'] | null>(null);
  const [selectedModel, setSelectedModel] = useState<RecognitionDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadIssue, setLoadIssue] = useState<LoadIssueKind>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [formState, setFormState] = useState({
    review_status: 'pending',
    manual_tags: '',
    operator_notes: '',
    recommended: false,
    cost_tier_override: '',
    visibility: 'default',
    badges: '',
  });

  useEffect(() => {
    setFilters(readInitialFilters(searchParams));
  }, [searchParams]);

  const updateUrl = useCallback((next: Partial<FilterState>) => {
    const merged: FilterState = { ...filters, ...next };
    const params = new URLSearchParams();
    if (merged.search) params.set('search', merged.search);
    if (merged.provider_id) params.set('provider_id', merged.provider_id);
    if (merged.review_status) params.set('review_status', merged.review_status);
    if (merged.in_hosted_catalog) params.set('in_hosted_catalog', merged.in_hosted_catalog);
    if (merged.source) params.set('source', merged.source);
    if (merged.quick_filter) params.set('quick_filter', merged.quick_filter);
    if (merged.page > 1) params.set('page', String(merged.page));
    if (merged.per_page !== DEFAULT_ADMIN_PAGE_SIZE) params.set('per_page', String(merged.per_page));
    if (merged.sort_by !== 'provider_id') params.set('sort_by', merged.sort_by);
    if (merged.sort_dir !== 'asc') params.set('sort_dir', merged.sort_dir);
    if (merged.model_id) params.set('model_id', merged.model_id);
    const query = params.toString();
    router.replace(query ? `/admin/model-intelligence?${query}` : '/admin/model-intelligence');
  }, [filters, router]);

  const loadModels = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setLoadIssue(null);
    try {
      const params = new URLSearchParams();
      if (filters.search) params.set('search', filters.search);
      if (filters.provider_id) params.set('provider_id', filters.provider_id);
      if (filters.review_status) params.set('review_status', filters.review_status);
      if (filters.in_hosted_catalog === 'true' || filters.in_hosted_catalog === 'false') {
        params.set('in_hosted_catalog', filters.in_hosted_catalog);
      }
      if (filters.source) params.set('source', filters.source);
      if (filters.quick_filter) params.set('quick_filter', filters.quick_filter);
      params.set('page', String(filters.page));
      params.set('per_page', String(filters.per_page));
      params.set('sort_by', filters.sort_by);
      params.set('sort_dir', filters.sort_dir);

      const response = await fetch(`/api/admin/recognition?${params.toString()}`, {
        credentials: 'include',
      });
      const contentType = response.headers.get('content-type') || '';
      if (
        response.status === 401 ||
        response.status === 403 ||
        response.redirected ||
        response.url.includes('/admin/login') ||
        (!contentType.includes('application/json') && response.ok)
      ) {
        setLoadIssue('auth');
        setModels([]);
        setTotal(0);
        setBundle(null);
        return;
      }
      if (!response.ok) {
        setLoadIssue('failed');
        throw new Error(t('error.failed_load'));
      }
      const payload = await response.json();
      const data: RecognitionResponse = payload.data;
      setModels(data.items || []);
      setTotal(data.total || 0);
      setPagination(data.pagination);
      setSortState(data.sort);
      setSummary(data.summary);
      setPricingConfig(data.pricing || null);
      setBundle(data.recognition_bundle);
    } catch (err) {
      setLoadIssue((current) => current || 'failed');
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [filters, t]);

  const loadModelDetail = useCallback(async () => {
    if (!filters.provider_id || !filters.model_id) {
      setSelectedModel(null);
      return;
    }
    try {
      const response = await fetch(
        `/api/admin/recognition/model?provider_id=${encodeURIComponent(filters.provider_id)}&model_id=${encodeURIComponent(filters.model_id)}`,
        { credentials: 'include' }
      );
      if (!response.ok) {
        throw new Error(t('error.failed_load'));
      }
      const payload = await response.json();
      const data: RecognitionDetail = payload.data;
      setSelectedModel(data);
      if (data.pricing) {
        setPricingConfig(data.pricing);
      }
      setFormState({
        review_status: data.annotation.review_status || 'pending',
        manual_tags: (data.annotation.manual_tags || []).join(', '),
        operator_notes: data.annotation.operator_notes || '',
        recommended: Boolean(data.annotation.recommended),
        cost_tier_override: data.annotation.cost_tier_override || '',
        visibility: data.annotation.visibility || 'default',
        badges: (data.annotation.badges || []).join(', '),
      });
    } catch (err) {
      setSelectedModel(null);
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    }
  }, [filters.model_id, filters.provider_id, t]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  useEffect(() => {
    void loadModelDetail();
  }, [loadModelDetail]);

  const providerOptions = useMemo(
    () => Array.from(new Set(models.map((item) => item.provider_id))).sort(),
    [models]
  );
  const adminSource = bundle?.admin_source;
  const failedSourceKeys = adminSource?.failed_sources || [];
  const adminFreshness = adminSource?.freshness_status || 'missing';
  const adminHealthStatus = adminSource?.health_status || 'error';
  const adminHealthIssues = adminSource?.health_issues || [];
  const adminFallback = adminSource?.fallback;
  const operatorAlerts = adminSource?.operator_alerts || [];
  const latestPublication = adminSource?.latest_publication;
  const recentPublications = adminSource?.recent_publications || [];
  const scopedProviderId = selectedModel?.provider_id || filters.provider_id || '';
  const sourceHealthLabel = adminSource?.source_keys?.length
    ? `${formatInteger(Math.max((adminSource.source_keys.length || 0) - failedSourceKeys.length, 0))}/${formatInteger(adminSource.source_keys.length)}`
    : notAvailableLabel;
  const sourceHealthDetail = adminSource?.source_keys?.length
    ? failedSourceKeys.length
      ? failedSourceKeys.join(', ')
      : t('admin.intelligence_all_sources_healthy', {}, 'All configured publisher sources succeeded in the latest bundle.')
    : t('admin.intelligence_no_sources_configured', {}, 'No publisher sources are currently configured.');
  const adminHealthNotice = !adminSource?.configured
    ? t(
        'admin.intelligence_source_unconfigured_desc',
        {},
        'Publisher execution is not configured in this cloud environment yet.'
      )
    : adminFreshness === 'expired'
      ? t(
          'admin.intelligence_source_expired_desc',
          {},
          'The latest intelligence bundle is beyond the freshness SLA and should not be treated as current without a refresh.'
        )
      : adminFreshness === 'stale'
        ? t(
            'admin.intelligence_source_stale_desc',
            {},
            'The latest intelligence bundle is still readable, but it is already older than the preferred freshness window.'
          )
        : failedSourceKeys.length > 0
          ? t(
              'admin.intelligence_source_partial_desc',
              {},
              'The latest publisher run completed with source failures. Review the failed source list before trusting the bundle as complete.'
            )
          : '';
  const publisherFallbackDetail = adminFallback?.previous_bundle_used
    ? t(
        'admin.publisher_fallback_previous_bundle',
        {},
        'Latest refresh retained the previous bundle instead of publishing a fully current run.'
      )
    : adminFallback?.cached_sources_used?.length
      ? `${t('admin.publisher_fallback_cached_sources', {}, 'Cached source fallback used for')}: ${adminFallback.cached_sources_used.join(', ')}`
      : t('admin.publisher_fallback_none', {}, 'No fallback bundle behavior was needed in the latest run.');

  const saveAnnotation = async () => {
    if (!selectedModel) {
      return;
    }
    setIsSaving(true);
    setSaveMessage(null);
    setError(null);
    try {
      const response = await fetch(
        '/api/admin/recognition/model/annotation',
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider_id: selectedModel.provider_id,
            model_id: selectedModel.model_id,
            review_status: formState.review_status,
            manual_tags: formState.manual_tags
              .split(',')
              .map((item) => item.trim())
              .filter(Boolean),
            operator_notes: formState.operator_notes,
            recommended: formState.recommended,
            cost_tier_override: formState.cost_tier_override,
            visibility: formState.visibility,
            badges: formState.badges
              .split(',')
              .map((item) => item.trim())
              .filter(Boolean),
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok || payload.status === 'error') {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.unexpected')));
      }
      setSaveMessage(t('common.saved', {}, 'Saved!'));
      await loadModelDetail();
      await loadModels();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.unexpected')));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_model_ops', {}, 'Model Ops')}
        title={t('admin.recognition_review_title', {}, 'Model intelligence')}
        description={t(
          'admin.recognition_review_desc',
          {},
          'Review intelligence bundles, failed sources, trends, evidence, and lightweight annotations from one bounded internal page.'
        )}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <div className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200">
              {t('admin.currency_cny', {}, 'CNY')}
            </div>
            <button
              type="button"
              onClick={() => void loadModels()}
              className="rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
            >
              {t('common.refresh', {}, 'Refresh')}
            </button>
          </div>
        )}
      >
          <BackofficeLayer
            title={t(
              'admin.recognition_review_boundary',
              {},
              'This bounded internal page reviews publisher intelligence and evidence only. It is not part of the v1 operator surface.'
            )}
          />
      </BackofficePrimaryPanel>

      <BackofficeMetricStrip
        items={[
          {
            label: t('common.models', {}, 'Models'),
            value: formatInteger(total),
            detail: t(
              'admin.recognition_review_total_desc',
              {},
              'Recognition rows currently published in the latest bundle.'
            ),
          },
          {
            label: t('admin.in_hosted_catalog', {}, 'In hosted catalog'),
            value: formatInteger(summary.hosted_catalog_total || 0),
            detail: t(
              'admin.recognition_review_hosted_desc',
              {},
              'Recognized rows that are already present in the hosted catalog.'
            ),
          },
          {
            label: t('admin.review_status_pending', {}, 'Pending'),
            value: formatInteger(summary.review_status_counts?.pending || 0),
            detail: t(
              'admin.recognition_review_pending_desc',
              {},
              'Rows that still need operator review before any hosted catalog decision.'
            ),
          },
          {
            label: t('admin.review_status_candidate', {}, 'Candidate'),
            value: formatInteger(summary.review_status_counts?.candidate || 0),
            detail: t(
              'admin.recognition_review_candidate_desc',
              {},
              'Rows operators marked as hosted-catalog candidates.'
            ),
          },
          {
            label: t('admin.recognition_review_low_confidence', {}, 'Low confidence'),
            value: formatInteger(summary.low_confidence_total || 0),
            detail: t(
              'admin.recognition_review_low_confidence_desc',
              {},
              'Rows below the current confidence threshold and likely to need follow-up.'
            ),
          },
          {
            label: t('admin.recognition_review_conflicts', {}, 'Conflicts'),
            value: formatInteger(summary.conflict_total || 0),
            detail: t(
              'admin.recognition_review_conflicts_desc',
              {},
              'Rows whose match keys collide with another recognition row.'
            ),
          },
          {
            label: t('admin.recognition_price_conflicts', {}, 'Price conflicts'),
            value: formatInteger(summary.price_conflict_total || 0),
            detail: t(
              'admin.recognition_price_conflicts_desc',
              {},
              'Rows whose intelligence sources disagree on token pricing.'
            ),
          },
          {
            label: t('admin.recognition_capability_conflicts', {}, 'Capability conflicts'),
            value: formatInteger(summary.capability_conflict_total || 0),
            detail: t(
              'admin.recognition_capability_conflicts_desc',
              {},
              'Rows whose intelligence sources disagree on model capability shape.'
            ),
          },
          {
            label: t('admin.recognition_new_models', {}, 'New models'),
            value: formatInteger(summary.new_models_total || 0),
            detail: t(
              'admin.recognition_new_models_desc',
              {},
              'Rows newly added since the previous intelligence snapshot.'
            ),
          },
          {
            label: t('admin.recognition_disappeared_models', {}, 'Disappeared models'),
            value: formatInteger(summary.disappeared_models_total || 0),
            detail: t(
              'admin.recognition_disappeared_models_desc',
              {},
              'Rows present in the previous intelligence snapshot but not in the current one.'
            ),
          },
          {
            label: t('admin.bundle_revision', {}, 'Intelligence bundle'),
            value: bundle?.revision || notAvailableLabel,
            detail: bundle?.published_at
              ? `${formatDate(bundle.published_at)} · ${compactChecksum(bundle?.checksum || '', notAvailableLabel)}`
              : compactChecksum(bundle?.checksum || '', notAvailableLabel),
          },
          {
            label: t('admin.recognition_intelligence_source', {}, 'Intelligence source'),
            value: translateRecognitionSourceKind(bundle?.admin_source?.kind || '', t),
            detail:
              bundle?.admin_source?.generated_at
                ? `${formatDate(bundle.admin_source.generated_at)} · ${formatInteger(bundle.admin_source.records_total || 0)}`
                : formatInteger(bundle?.admin_source?.records_total || 0),
          },
          {
            label: t('admin.pricing', {}, 'Pricing'),
            value: pricingCurrency,
            detail: pricingConfig
              ? `${t('admin.price_unit_per_1m_tokens', {}, 'Per 1M tokens')} · 1 USD ≈ ${formatRecognitionPrice(1, { currency: 'CNY', pricing: pricingConfig })}`
              : t('admin.price_not_available', {}, 'Price not available'),
          },
        ]}
      />

      <BackofficeLayer
        title={t('admin.recognition_source_summary', {}, 'Source summary')}
        description={
          adminSource?.source_keys?.length
            ? `${translateRecognitionSourceKind(adminSource.kind || '', t)} · ${adminSource.source_keys.join(', ')}`
            : translateRecognitionSourceKind(adminSource?.kind || '', t)
        }
      />

      <BackofficeSectionPanel>
        <div id="source-summary-bridge" />
        <BackofficeLayer
          eyebrow={t('admin.provider_connections', {}, 'Source connections')}
          title={t('admin.model_intelligence_provider_bridge_title', {}, 'Source repair bridge')}
          description={t(
            'admin.model_intelligence_provider_bridge_desc',
            {},
            'Use this bridge when the next step belongs in source repair rather than review.'
          )}
        />
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <BackofficeStackCard>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('admin.intelligence_source_health', {}, 'Source health')}
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{sourceHealthLabel}</p>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{sourceHealthDetail}</p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('admin.intelligence_failed_sources', {}, 'Failed sources')}
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{formatInteger(failedSourceKeys.length)}</p>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {failedSourceKeys.length
                ? failedSourceKeys.join(', ')
                : t('admin.intelligence_failed_sources_none', {}, 'No failed publisher sources in the latest run summary.')}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('admin.model_intelligence_active_source_keys', {}, 'Active source keys')}
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
              {formatInteger(adminSource?.source_keys?.length || 0)}
            </p>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {(adminSource?.source_keys || []).length
                ? (adminSource?.source_keys || []).join(', ')
                : t('admin.intelligence_no_sources_configured', {}, 'No publisher sources are currently configured.')}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('admin.recognition_intelligence_source', {}, 'Source kind')}
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
              {translateRecognitionSourceKind(adminSource?.kind || '', t)}
            </p>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {adminSource?.generated_at ? formatDate(adminSource.generated_at) : t('common.not_available', {}, 'N/A')}
            </p>
          </BackofficeStackCard>
        </div>
      </BackofficeSectionPanel>

      {adminHealthNotice ? (
        <BackofficeSectionPanel>
          <div
            className={cn(
              'rounded-2xl border px-4 py-3 text-sm',
              adminFreshness === 'expired' || failedSourceKeys.length > 0
                ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200'
                : adminFreshness === 'stale'
                  ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200'
                  : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-200'
            )}
          >
            {adminHealthNotice}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {operatorAlerts.length > 0 ? (
        <BackofficeSectionPanel>
          <BackofficeLayer
            title={t('admin.publisher_operator_alerts', {}, 'Operator alerts')}
            description={t(
              'admin.publisher_operator_alerts_desc',
              {},
              'Current publisher issues that need follow-up before you treat this intelligence snapshot as fully healthy.'
            )}
          />
          <div className="mt-4 space-y-2">
            {operatorAlerts.map((alert, index) => (
              <div
                key={`${alert.code}-${index}`}
                className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/40"
              >
                <div className="space-y-1">
                  <div className="font-medium text-slate-900 dark:text-slate-100">
                    {translateOperatorAlertCode(alert.code, t, alert)}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {alert.hours_old != null ? `${alert.hours_old}h` : notAvailableLabel}
                  </div>
                </div>
                <BackofficeStatusBadge
                  status={toBackofficeAlertStatus(alert.severity)}
                  label={translateHealthStatus(alert.severity === 'error' ? 'error' : 'warning', t)}
                />
              </div>
            ))}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      <BackofficeMetricStrip
        items={[
          {
            label: t('admin.publisher_status', {}, 'Publisher status'),
            value: translateHealthStatus(adminHealthStatus, t),
            detail: adminHealthIssues.length
              ? adminHealthIssues.map((issue) => translatePublisherIssue(issue, t)).join(' · ')
              : t(
                  'admin.publisher_status_ok_desc',
                  {},
                  'Publisher freshness, source coverage, and current bundle state are all healthy.'
                ),
          },
          {
            label: t('admin.intelligence_freshness', {}, 'Publisher freshness'),
            value: translateFreshnessStatus(adminFreshness, t),
            detail: adminSource?.generated_at
              ? `${formatDate(adminSource.generated_at)} · ${adminSource.hours_old != null ? `${adminSource.hours_old}h` : notAvailableLabel}`
              : t('admin.intelligence_bundle_missing', {}, 'No published intelligence bundle detected yet.'),
          },
          {
            label: t('admin.intelligence_failed_sources', {}, 'Failed sources'),
            value: formatInteger(failedSourceKeys.length),
            detail: failedSourceKeys.length
              ? failedSourceKeys.join(', ')
              : t('admin.intelligence_failed_sources_none', {}, 'No failed publisher sources in the latest run summary.'),
          },
          {
            label: t('admin.intelligence_source_health', {}, 'Source health'),
            value: sourceHealthLabel,
            detail: sourceHealthDetail,
          },
          {
            label: t('admin.intelligence_latest_publication', {}, 'Latest publication'),
            value: latestPublication?.revision || notAvailableLabel,
            detail: latestPublication?.generated_at
              ? `${formatDate(latestPublication.generated_at)} · ${compactChecksum(latestPublication.checksum || '', notAvailableLabel)}`
              : t('admin.intelligence_latest_publication_missing', {}, 'No persisted cloud publication has been recorded yet.'),
          },
          {
            label: t('admin.publisher_fallback', {}, 'Fallback behavior'),
            value: adminFallback?.previous_bundle_used
              ? t('admin.publisher_fallback_previous', {}, 'Previous bundle')
              : adminFallback?.cached_sources_used?.length
                ? t('admin.publisher_fallback_cached', {}, 'Cached source data')
                : t('admin.publisher_fallback_none_short', {}, 'None'),
            detail: publisherFallbackDetail,
          },
        ].map((item) => ({
          ...item,
          value:
            item.label === t('admin.publisher_status', {}, 'Publisher status') ? (
              <BackofficeStatusBadge
                status={toBackofficeHealthStatus(adminHealthStatus)}
                label={String(item.value)}
              />
            ) : item.label === t('admin.intelligence_freshness', {}, 'Publisher freshness') ? (
              <BackofficeStatusBadge
                status={toBackofficeFreshnessStatus(adminFreshness)}
                label={String(item.value)}
              />
            ) : (
              item.value
            ),
        }))}
      />

      <details className="rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
        <summary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-300">
          {t('admin.model_intelligence_source_detail_toggle', {}, 'Inspect source, publication, and trend details')}
        </summary>

      {recentPublications.length > 0 ? (
        <BackofficeSectionPanel className="mt-4">
          <BackofficeLayer
            title={t('admin.publisher_recent_publications', {}, 'Publication audit')}
            description={t(
              'admin.publisher_recent_publications_desc',
              {},
              'Use this short audit trail to confirm publication cadence, fallback use, and source failure patterns.'
            )}
          />
          <div className="mt-4 space-y-2">
            {recentPublications.slice(0, 3).map((publication) => (
              <div
                key={`${publication.revision || 'unknown'}-${publication.generated_at || 'unknown'}`}
                className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/40"
              >
                <div className="space-y-1">
                  <p className="font-medium text-slate-900 dark:text-slate-100">
                    {publication.revision || notAvailableLabel}
                  </p>
                  <p className="text-slate-600 dark:text-slate-300">
                    {publication.generated_at
                      ? `${formatDate(publication.generated_at)} · ${formatInteger(publication.records_total || 0)}`
                      : formatInteger(publication.records_total || 0)}
                  </p>
                  <p className="text-slate-500 dark:text-slate-400">
                    {(publication.source_keys || []).length
                      ? (publication.source_keys || []).join(', ')
                      : t('admin.intelligence_no_sources_configured', {}, 'No publisher sources are currently configured.')}
                  </p>
                  {publication.failed_sources?.length ? (
                    <p className="text-xs text-rose-600 dark:text-rose-300">
                      {t('admin.intelligence_failed_sources', {}, 'Failed sources')}: {publication.failed_sources.join(', ')}
                    </p>
                  ) : null}
                  {publication.fallback?.previous_bundle_used ? (
                    <p className="text-xs text-amber-600 dark:text-amber-300">
                      {t('admin.publisher_fallback_previous_bundle', {}, 'Latest refresh retained the previous bundle instead of publishing a fully current run.')}
                    </p>
                  ) : publication.fallback?.cached_sources_used?.length ? (
                    <p className="text-xs text-amber-600 dark:text-amber-300">
                      {t('admin.publisher_fallback_cached_sources', {}, 'Cached source fallback used for')}: {publication.fallback.cached_sources_used.join(', ')}
                    </p>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <BackofficeStatusBadge
                    status={toBackofficeFreshnessStatus(publication.freshness_status || 'missing')}
                    label={translateFreshnessStatus(publication.freshness_status || 'missing', t)}
                  />
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {publication.hours_old != null ? `${publication.hours_old}h` : notAvailableLabel}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {(summary.sources || []).length > 0 ? (
        <BackofficeMetricStrip
          items={(summary.sources || []).map((source) => ({
            label: translateRecognitionEvidenceSource(source, t),
            value: formatInteger(summary.source_counts?.[source] || 0),
            detail: t(
              'admin.recognition_source_models_desc',
              {},
              'Recognition rows currently attributed to this intelligence source.'
            ),
          }))}
        />
      ) : null}

      {(summary.source_trends || []).length > 0 ? (
        <BackofficeSectionPanel>
          <BackofficeLayer
            title={t('admin.recognition_source_trends', {}, 'Source trends')}
            description={t(
              'admin.recognition_source_trends_desc',
              {},
              'Compare current source totals with the previous intelligence snapshot.'
            )}
          />
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {summary.source_trends.map((trend) => (
              <div
                key={trend.source}
                className="rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"
              >
                <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  {translateRecognitionEvidenceSource(trend.source, t)}
                </div>
                <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                  {formatInteger(trend.current_total || 0)}
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t('admin.delta_label', {}, 'Delta')}: {trend.delta > 0 ? `+${formatInteger(trend.delta)}` : formatInteger(trend.delta)}
                </div>
              </div>
            ))}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {(summary.disappeared_models || []).length > 0 ? (
        <BackofficeSectionPanel>
          <BackofficeLayer
            title={t('admin.recognition_disappeared_models', {}, 'Disappeared models')}
            description={t(
              'admin.recognition_disappeared_models_desc',
              {},
              'Rows present in the previous intelligence snapshot but not in the current one.'
            )}
          />
          <div className="mt-4 flex flex-wrap gap-2">
            {summary.disappeared_models.map((item) => (
              <BackofficeTag key={`${item.provider_id}:${item.model_id}`}>
                {item.provider_id}/{item.model_id}
              </BackofficeTag>
            ))}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {(summary.source_runs || []).length > 0 ? (
        <BackofficeSectionPanel>
          <div id="source-failure-panel" />
          <BackofficeLayer
            title={t('admin.recognition_source_runs', {}, 'Source failure panel')}
            description={t(
              'admin.recognition_source_runs_desc',
              {},
              'Inspect the latest source-level run status before trusting the current intelligence snapshot.'
            )}
          />
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {summary.source_runs.map((run) => (
              <div
                key={run.run_id || run.source_key || run.source || run.generated_at}
                className="rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"
              >
                <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  {translateRecognitionEvidenceSource(run.source || run.source_key || '', t)}
                </div>
                <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                  {formatInteger(run.records_fetched ?? run.records_total ?? 0)}
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {run.generated_at ? formatDate(run.generated_at) : notAvailableLabel}
                </div>
                <div className="mt-2">
                  <BackofficeStatusBadge
                    status={toBackofficeAlertStatus(run.status === 'error' ? 'error' : run.status === 'warning' ? 'warning' : 'ok')}
                    label={run.status || notAvailableLabel}
                  />
                </div>
              </div>
            ))}
          </div>
        </BackofficeSectionPanel>
      ) : null}
      </details>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
        <BackofficeSectionPanel>
          <BackofficeLayer
            title={t('admin.recognition_review_filters', {}, 'Model intelligence filters')}
            description={t(
              'admin.recognition_review_filters_desc',
              {},
              'Filter by provider, review state, hosted catalog presence, or evidence source.'
            )}
          />
          <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <span>{t('common.search', {}, 'Search')}</span>
              <input
                value={filters.search}
                onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
                onBlur={() => updateUrl({ search: filters.search, page: 1 })}
                placeholder={t('admin.recognition_review_search_placeholder', {}, 'Model ID, alias, source')}
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
              />
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <span>{t('common.provider', {}, 'Provider')}</span>
              <select
                value={filters.provider_id}
                onChange={(event) => updateUrl({ provider_id: event.target.value, page: 1 })}
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
              >
                <option value="">{t('admin.all_providers', {}, 'All providers')}</option>
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <span>{t('admin.review_status', {}, 'Review status')}</span>
              <select
                value={filters.review_status}
                onChange={(event) => updateUrl({ review_status: event.target.value, page: 1 })}
                className="input w-full"
              >
                <option value="">{t('admin.review_status_any', {}, 'Review status: any')}</option>
                <option value="pending">{translateReviewStatus('pending', t)}</option>
                <option value="reviewed">{translateReviewStatus('reviewed', t)}</option>
                <option value="candidate">{translateReviewStatus('candidate', t)}</option>
                <option value="suppressed">{translateReviewStatus('suppressed', t)}</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <span>{t('admin.in_hosted_catalog', {}, 'In hosted catalog')}</span>
              <select
                value={filters.in_hosted_catalog}
                onChange={(event) => updateUrl({ in_hosted_catalog: event.target.value, page: 1 })}
                className="input w-full"
              >
                <option value="">{t('admin.in_hosted_catalog_any', {}, 'Hosted catalog: any')}</option>
                <option value="true">{t('common.yes', {}, 'Yes')}</option>
                <option value="false">{t('common.no', {}, 'No')}</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <span>{t('admin.source_label', {}, 'Source')}</span>
              <select
                value={filters.source}
                onChange={(event) => updateUrl({ source: event.target.value, page: 1 })}
                className="input w-full"
              >
                <option value="">{t('admin.all_sources', {}, 'All sources')}</option>
                {(summary.sources || []).map((source) => (
                  <option key={source} value={source}>
                    {translateRecognitionEvidenceSource(source, t)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {quickFilters.map((filter) => (
              <BackofficeFilterPill
                key={filter.value || 'all'}
                active={filters.quick_filter === filter.value || (!filters.quick_filter && !filter.value)}
                tone={filter.tone}
                onClick={() => updateUrl({ quick_filter: filter.value, page: 1 })}
              >
                {filter.label}
              </BackofficeFilterPill>
            ))}
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel>
          <BackofficeLayer
            title={t('admin.recognition_review_table_title', {}, 'Model review rows')}
            description={t(
              'admin.recognition_review_range',
              {
                start: formatInteger(pagination.offset + (models.length > 0 ? 1 : 0)),
                end: formatInteger(pagination.offset + models.length),
                total: formatInteger(total),
              },
              'Showing {{start}}-{{end}} of {{total}} recognition rows.'
            )}
          />
          <div className="space-y-3">
            {error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-200">
                {error}
              </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
              <span>{t('admin.sort_label', {}, 'Sort')}</span>
              <select
                value={filters.sort_by}
                onChange={(event) => updateUrl({ sort_by: event.target.value, page: 1 })}
                className="input"
              >
                <option value="provider_id">{t('admin.sort_provider', {}, 'Provider')}</option>
                <option value="model_id">{t('admin.sort_model_id', {}, 'Model ID')}</option>
                <option value="confidence">{t('admin.sort_confidence', {}, 'Confidence')}</option>
                <option value="review_status">{t('admin.sort_review_status', {}, 'Review status')}</option>
                <option value="updated_at">{t('admin.sort_updated_at', {}, 'Updated')}</option>
                <option value="in_hosted_catalog">{t('admin.sort_hosted_presence', {}, 'Hosted presence')}</option>
              </select>
              <select
                value={filters.sort_dir}
                onChange={(event) => updateUrl({ sort_dir: event.target.value, page: 1 })}
                className="input"
              >
                <option value="asc">{t('admin.sort_asc', {}, 'Ascending')}</option>
                <option value="desc">{t('admin.sort_desc', {}, 'Descending')}</option>
              </select>
              <select
                value={String(filters.per_page)}
                onChange={(event) => updateUrl({ per_page: Number.parseInt(event.target.value, 10), page: 1 })}
                className="input"
              >
                <option value="10">10 / {t('admin.page_label', {}, 'page')}</option>
                <option value="25">25 / {t('admin.page_label', {}, 'page')}</option>
                <option value="50">50 / {t('admin.page_label', {}, 'page')}</option>
                <option value="100">100 / {t('admin.page_label', {}, 'page')}</option>
              </select>
            </div>

            <div className="space-y-3">
              {isLoading ? (
                <div className="rounded-3xl border border-slate-200 bg-white/85 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/70 dark:text-slate-400">
                  {t('common.loading', {}, 'Loading...')}
                </div>
              ) : models.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-8 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-400">
                  {loadIssue === 'auth' ? (
                    <div className="space-y-3">
                      <div className="font-medium text-slate-700 dark:text-slate-200">
                        {t('admin.recognition_review_empty_auth_title', {}, 'Admin session required')}
                      </div>
                      <div>
                        {t(
                          'admin.recognition_review_empty_auth_desc',
                          {},
                          'Model intelligence data is available, but this session cannot read it right now. Sign in again and reopen /admin/model-intelligence.'
                        )}
                      </div>
                      <div>
                        <button
                          type="button"
                          onClick={() => {
                            window.location.href = '/admin/login?redirect=%2Fadmin%2Fmodel-intelligence';
                          }}
                          className="btn btn-secondary"
                        >
                          {t('admin.open_admin_login', {}, 'Open admin login')}
                        </button>
                      </div>
                    </div>
                  ) : !bundle?.revision
                    ? t('admin.recognition_review_empty_no_bundle', {}, 'Intelligence bundle is not available yet.')
                    : bundle?.admin_source?.kind === 'unconfigured'
                      ? t(
                          'admin.recognition_review_empty_no_source',
                          {},
                          'Model intelligence source is not configured yet. Enable a real refresh source or a development review sample before using /admin/model-intelligence.'
                        )
                    : filters.search ||
                        filters.provider_id ||
                        filters.review_status ||
                        filters.in_hosted_catalog ||
                        filters.source ||
                        filters.quick_filter
                      ? t('admin.recognition_review_empty_filtered', {}, 'No model intelligence rows matched the current filters.')
                      : t('admin.recognition_review_empty', {}, 'No model intelligence rows are available for review yet.')}
                </div>
              ) : (
                models.map((item) => {
                  const selected =
                    filters.provider_id === item.provider_id && filters.model_id === item.model_id;
                  const hostedCurationReady = isHostedCurationReady(item);
                  return (
                    <button
                      key={`${item.provider_id}:${item.model_id}`}
                      type="button"
                      onClick={() => updateUrl({ provider_id: item.provider_id, model_id: item.model_id })}
                      className={cn(
                        'w-full rounded-3xl border px-4 py-4 text-left transition',
                        selected
                          ? 'border-blue-400 bg-blue-50/70 shadow-sm dark:border-blue-500 dark:bg-blue-950/20'
                          : 'border-slate-200 bg-white/85 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/70 dark:hover:border-slate-700 dark:hover:bg-slate-900/60'
                      )}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="space-y-1">
                          <BackofficeIdentifier
                            value={item.model_id}
                            className="text-sm font-semibold text-slate-900 dark:text-white"
                          />
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            <BackofficeIdentifier value={item.provider_id} className="text-xs text-slate-500 dark:text-slate-400" /> · {item.model_type || notAvailableLabel} · {item.preview_type || notAvailableLabel}
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <ReviewStatusBadge status={item.annotation.review_status} t={t} />
                          <AdminSemanticBadge tone={item.in_hosted_catalog ? 'success' : 'neutral'}>
                            {item.in_hosted_catalog
                              ? t('admin.in_hosted_catalog_short', {}, 'Hosted')
                              : t('admin.not_in_hosted_catalog_short', {}, 'Review only')}
                          </AdminSemanticBadge>
                          {item.has_match_conflict ? (
                            <AdminSemanticBadge tone="danger">
                              {t('admin.match_conflict_short', {}, 'Conflict')}
                            </AdminSemanticBadge>
                          ) : null}
                          {!item.in_hosted_catalog ? (
                            <AdminSemanticBadge tone="neutral">
                              {translateWhyNotInHostedCatalog(item.why_not_in_hosted_catalog, t)}
                            </AdminSemanticBadge>
                          ) : null}
                          {hostedCurationReady ? (
                            <AdminSemanticBadge tone="accent">
                              {t('admin.next_step_curate_hosted_short', {}, 'Next: curate hosted')}
                            </AdminSemanticBadge>
                          ) : null}
                          {item.is_new_since_previous_snapshot ? (
                            <AdminSemanticBadge tone="success">
                              {t('admin.quick_filter_new_models', {}, 'New models')}
                            </AdminSemanticBadge>
                          ) : null}
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
                        <span>
                          {t('admin.source_label', {}, 'Source')}: {translateRecognitionEvidenceSource(item.source || '', t)}
                        </span>
                        <span>{t('admin.sort_confidence', {}, 'Confidence')}: {item.confidence.toFixed(2)}</span>
                        <span>{formatRecognitionPriceSummary(item, { currency: pricingCurrency, pricing: pricingConfig, t })}</span>
                        <span>
                          {t('admin.recognition_source_coverage', {}, 'Source coverage')}: {formatInteger(item.source_coverage_count || 0)}
                        </span>
                        <span>
                          {t('admin.primary_evidence', {}, 'Primary evidence')}:{' '}
                          {item.primary_evidence?.source || notAvailableLabel}
                        </span>
                        <span>
                          {t('admin.evidence_source_count', {}, 'Evidence sources')}:{' '}
                          {formatInteger(item.evidence_source_count || 0)}
                        </span>
                        <span>{t('admin.annotation_updated_at', {}, 'Updated')}: {item.annotation.updated_at ? formatDate(item.annotation.updated_at) : notAvailableLabel}</span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>

            <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
              <button
                type="button"
                disabled={pagination.page <= 1}
                onClick={() => updateUrl({ page: Math.max(1, pagination.page - 1) })}
                className="rounded-full border border-slate-200 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700"
              >
                {t('common.previous', {}, 'Previous')}
              </button>
              <span>
                {t('admin.page_label', {}, 'Page')} {pagination.page} / {pagination.pages_total}
              </span>
              <button
                type="button"
                disabled={pagination.page >= pagination.pages_total}
                onClick={() => updateUrl({ page: pagination.page + 1 })}
                className="rounded-full border border-slate-200 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700"
              >
                {t('common.next', {}, 'Next')}
              </button>
            </div>
          </div>
        </BackofficeSectionPanel>

        <BackofficeStackCard>
          <BackofficeLayer
            title={t('admin.detail', {}, 'Detail')}
            description={t(
              'admin.recognition_review_inspector_desc',
              {},
              'Inspect publisher intelligence detail and record lightweight operator annotations.'
            )}
          />
          {selectedModel ? (
            <div className="mt-6 space-y-6">
              <BackofficeLayer
                title={selectedModel.model_id}
                description={`${selectedModel.provider_id} · ${translateRecognitionEvidenceSource(selectedModel.source || '', t)}`}
              />

              <div className="grid gap-3 text-sm md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                    {t('admin.bundle_revision', {}, 'Intelligence bundle')}
                  </div>
                  <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                    {selectedModel.recognition_bundle.revision}
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {selectedModel.recognition_bundle.published_at
                      ? `${formatDate(selectedModel.recognition_bundle.published_at)} · ${compactChecksum(selectedModel.recognition_bundle.checksum, notAvailableLabel)}`
                      : compactChecksum(selectedModel.recognition_bundle.checksum, notAvailableLabel)}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                    {t('admin.in_hosted_catalog', {}, 'In hosted catalog')}
                  </div>
                  <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                    {selectedModel.in_hosted_catalog
                      ? t('common.yes', {}, 'Yes')
                      : t('common.no', {}, 'No')}
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {selectedModel.in_hosted_catalog
                      ? `${selectedModel.hosted_catalog.provider_id} · ${selectedModel.hosted_catalog.feature || notAvailableLabel}`
                      : translateWhyNotInHostedCatalog(selectedModel.why_not_in_hosted_catalog, t)}
                  </div>
                </div>
              </div>

              {selectedModel.in_hosted_catalog ? (
                <div className="space-y-3">
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">
                    {t('admin.hosted_metadata_snapshot', {}, 'Hosted metadata snapshot')}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <HostedMetadataBadges metadata={selectedModel.hosted_metadata} t={t} />
                  </div>
                </div>
              ) : null}

              <div className="space-y-3">
                <div className="rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                    {t('admin.short_description', {}, 'Short description')}
                  </div>
                  <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                    {selectedModel.short_description || notAvailableLabel}
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {selectedModel.best_for || notAvailableLabel}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(selectedModel.supports || []).map((support) => (
                    <BackofficeTag key={support}>{support}</BackofficeTag>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">
                  {t('admin.pricing', {}, 'Pricing')}
                </div>
                <div className="grid gap-3 text-sm md:grid-cols-2">
                  <div className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                    <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                      {t('admin.price_input', {}, 'Input')}
                    </div>
                    <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                      {formatRecognitionPrice(selectedModel.price_input, { currency: pricingCurrency, pricing: pricingConfig })}
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {selectedModel.price_source
                        ? `${selectedModel.price_source} · ${t('admin.price_unit_per_1m_tokens', {}, 'Per 1M tokens')}`
                        : t('admin.price_unit_per_1m_tokens', {}, 'Per 1M tokens')}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                    <div className="text-xs uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                      {t('admin.price_output', {}, 'Output')}
                    </div>
                    <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                      {formatRecognitionPrice(selectedModel.price_output, { currency: pricingCurrency, pricing: pricingConfig })}
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {selectedModel.price_updated_at
                        ? `${formatDate(selectedModel.price_updated_at)} · ${t('admin.sort_confidence', {}, 'Confidence')}: ${(selectedModel.price_confidence || 0).toFixed(2)}`
                        : pricingConfig
                          ? `1 USD ≈ ${formatRecognitionPrice(1, { currency: 'CNY', pricing: pricingConfig })}`
                          : t('admin.price_not_available', {}, 'Price not available')}
                    </div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
                  <div className="font-medium text-slate-900 dark:text-white">
                    {selectedModel.price_summary || t('admin.price_not_available', {}, 'Price not available')}
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {selectedModel.has_price_conflict
                      ? t(
                          'admin.recognition_price_conflict_warning',
                          {},
                          'Multiple intelligence sources disagree on pricing for this model.'
                        )
                      : t(
                          'admin.recognition_price_conflict_clear',
                          {},
                          'Current intelligence sources agree on pricing or only one source supplied price data.'
                        )}
                  </div>
                </div>
                {selectedModel.price_sources?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedModel.price_sources.map((source) => (
                      <BackofficeTag
                        key={`${source.source}-${source.price_source}`}
                        tone="info"
                      >
                        {translateRecognitionEvidenceSource(source.source, t)} · {formatRecognitionPrice(source.price_input, { currency: pricingCurrency, pricing: pricingConfig })} / {formatRecognitionPrice(source.price_output, { currency: pricingCurrency, pricing: pricingConfig })}
                      </BackofficeTag>
                    ))}
                  </div>
                ) : null}
              </div>

              {isHostedCurationReady(selectedModel) ? (
                <div className="rounded-3xl border border-blue-200 bg-blue-50/80 px-4 py-4 dark:border-blue-900/40 dark:bg-blue-950/20">
                  <div className="text-sm font-semibold text-blue-900 dark:text-blue-100">
                    {t('admin.recognition_handoff_title', {}, 'Ready for platform model curation')}
                  </div>
                  <div className="mt-1 text-sm text-blue-800/90 dark:text-blue-200/90">
                    {t(
                      'admin.recognition_handoff_desc',
                      {},
                      'This intelligence row is marked as candidate and has no current hosted-catalog blocker. Continue in /admin/models for platform-serving curation.'
                    )}
                  </div>
                  <div className="mt-3">
                    <button
                      type="button"
                      onClick={() =>
                        window.open(
                          getHostedModelsHref(selectedModel.provider_id, selectedModel.model_id),
                          '_blank',
                          'noopener,noreferrer'
                        )
                      }
                      className="btn btn-primary"
                    >
                      {t('admin.curate_in_hosted_catalog', {}, 'Curate in hosted catalog')}
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="space-y-3">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">
                  {t('admin.evidence', {}, 'Evidence')}
                </div>
                {selectedModel.primary_evidence ? (
                  <div className="rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
                    <div className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                      {t('admin.primary_evidence', {}, 'Primary evidence')}
                    </div>
                    <div className="mt-1 font-semibold text-slate-900 dark:text-white">
                      {selectedModel.primary_evidence.source || notAvailableLabel}
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {t('admin.sort_confidence', {}, 'Confidence')}: {(selectedModel.primary_evidence.confidence || 0).toFixed(2)}
                    </div>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {selectedModel.evidence.length > 0 ? (
                    selectedModel.evidence.map((item, index) => (
                      <BackofficeTag
                        key={`${item.source}-${index}`}
                        tone="info"
                      >
                        {item.source || notAvailableLabel} · {(item.confidence || 0).toFixed(2)}
                      </BackofficeTag>
                    ))
                  ) : (
                    <span className="text-sm text-slate-500 dark:text-slate-400">
                      {t('admin.no_evidence', {}, 'No evidence')}
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-3">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">
                  {t('admin.capabilities', {}, 'Capabilities')}
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(selectedModel.capabilities || {}).map(([key, value]) => (
                    <BackofficeTag
                      key={key}
                      tone={value ? 'success' : 'neutral'}
                    >
                      {key}: {value ? t('common.yes', {}, 'Yes') : t('common.no', {}, 'No')}
                    </BackofficeTag>
                  ))}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {selectedModel.has_capability_conflict
                    ? t(
                        'admin.recognition_capability_conflict_warning',
                        {},
                        'Multiple intelligence sources disagree on this model’s capability shape.'
                      )
                    : t(
                        'admin.recognition_capability_conflict_clear',
                        {},
                        'Current intelligence sources agree on capability shape or only one source supplied capability data.'
                      )}
                </div>
                {selectedModel.capability_sources?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedModel.capability_sources.map((source) => (
                      <BackofficeTag
                        key={`${source.source}-${source.model_type}-${source.preview_type}`}
                        tone="info"
                      >
                        {translateRecognitionEvidenceSource(source.source, t)} · {source.model_type || notAvailableLabel} / {source.preview_type || notAvailableLabel}
                      </BackofficeTag>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="space-y-3">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">
                  {t('admin.aliases', {}, 'Aliases')}
                </div>
                <div className="flex flex-wrap gap-2">
                  {(selectedModel.aliases || []).length > 0 ? (
                    selectedModel.aliases.map((alias) => (
                      <BackofficeTag key={alias}>
                        {alias}
                      </BackofficeTag>
                    ))
                  ) : (
                    <span className="text-sm text-slate-500 dark:text-slate-400">{notAvailableLabel}</span>
                  )}
                </div>
              </div>

              {selectedModel.has_match_conflict ? (
                <div className="space-y-3">
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">
                    {t('admin.match_conflicts', {}, 'Match conflicts')}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedModel.match_conflict_keys.map((conflictKey) => (
                      <BackofficeTag key={conflictKey} tone="danger">
                        {conflictKey}
                      </BackofficeTag>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="grid gap-4">
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <span>{t('admin.review_status', {}, 'Review status')}</span>
                  <select
                    value={formState.review_status}
                    onChange={(event) => setFormState((current) => ({ ...current, review_status: event.target.value }))}
                    className="input w-full"
                  >
                    <option value="pending">{translateReviewStatus('pending', t)}</option>
                    <option value="reviewed">{translateReviewStatus('reviewed', t)}</option>
                    <option value="candidate">{translateReviewStatus('candidate', t)}</option>
                    <option value="suppressed">{translateReviewStatus('suppressed', t)}</option>
                  </select>
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t(
                      'admin.review_status_help',
                      {},
                      'Pending: not reviewed yet. Reviewed: checked but not ready for platform serving. Candidate: ready to hand off into /admin/models. Suppressed: do not promote.'
                    )}
                  </p>
                </label>

                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <span>{t('admin.recommended', {}, 'Recommended')}</span>
                  <BackofficeFilterPill
                    active={formState.recommended}
                    tone="success"
                    className="w-fit"
                    onClick={() => setFormState((current) => ({ ...current, recommended: !current.recommended }))}
                  >
                    {formState.recommended ? t('common.yes', {}, 'Yes') : t('common.no', {}, 'No')}
                  </BackofficeFilterPill>
                </label>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                    <span>{t('admin.cost_tier', {}, 'Cost tier override')}</span>
                    <select
                      value={formState.cost_tier_override}
                      onChange={(event) => setFormState((current) => ({ ...current, cost_tier_override: event.target.value }))}
                      className="input w-full"
                    >
                      <option value="">{t('common.not_set', {}, 'Not set')}</option>
                      <option value="budget">{t('admin.cost_tier_budget', {}, 'Budget')}</option>
                      <option value="balanced">{t('admin.cost_tier_balanced', {}, 'Balanced')}</option>
                      <option value="premium">{t('admin.cost_tier_premium', {}, 'Premium')}</option>
                    </select>
                  </label>

                  <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                    <span>{t('admin.visibility', {}, 'Visibility')}</span>
                    <select
                      value={formState.visibility}
                      onChange={(event) => setFormState((current) => ({ ...current, visibility: event.target.value }))}
                      className="input w-full"
                    >
                      <option value="default">{t('admin.visibility_default', {}, 'Default')}</option>
                      <option value="advanced">{t('admin.visibility_advanced', {}, 'Advanced')}</option>
                      <option value="hidden">{t('admin.visibility_hidden', {}, 'Hidden')}</option>
                    </select>
                  </label>
                </div>

                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <span>{t('admin.badges', {}, 'Badges')}</span>
                  <input
                    value={formState.badges}
                    onChange={(event) => setFormState((current) => ({ ...current, badges: event.target.value }))}
                    placeholder={t('admin.badges_placeholder', {}, 'comma-separated badges')}
                    className="input w-full"
                  />
                </label>

                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <span>{t('admin.manual_tags', {}, 'Manual tags')}</span>
                  <input
                    list="recognition-manual-tag-suggestions"
                    value={formState.manual_tags}
                    onChange={(event) => setFormState((current) => ({ ...current, manual_tags: event.target.value }))}
                    placeholder={t('admin.manual_tags_placeholder', {}, 'comma-separated tags')}
                    className="input w-full"
                  />
                  <datalist id="recognition-manual-tag-suggestions">
                    {(summary.manual_tag_suggestions || []).map((tag) => (
                      <option key={tag} value={tag} />
                    ))}
                  </datalist>
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t(
                      'admin.manual_tags_help',
                      {},
                      'Prefer the fixed tags: candidate, needs_followup, vision, image, embedding, oss. Add new tags only when a real operator workflow needs them.'
                    )}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(summary.manual_tag_suggestions || []).map((tag) => (
                      <BackofficeFilterPill
                        key={tag}
                        onClick={() =>
                          setFormState((current) => {
                            const existing = current.manual_tags
                              .split(',')
                              .map((item) => item.trim())
                              .filter(Boolean);
                            if (existing.includes(tag)) {
                              return current;
                            }
                            return {
                              ...current,
                              manual_tags: [...existing, tag].join(', '),
                            };
                          })
                        }
                        active={formState.manual_tags
                          .split(',')
                          .map((item) => item.trim())
                          .filter(Boolean)
                          .includes(tag)}
                        tone="info"
                      >
                        + {tag}
                      </BackofficeFilterPill>
                    ))}
                  </div>
                </label>

                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <span>{t('admin.operator_notes', {}, 'Operator notes')}</span>
                  <textarea
                    value={formState.operator_notes}
                    onChange={(event) => setFormState((current) => ({ ...current, operator_notes: event.target.value }))}
                    rows={5}
                    placeholder={t('admin.recognition_operator_notes_placeholder', {}, 'Notes for publisher intelligence review only. Platform model metadata belongs in /admin/models.')}
                    className="w-full rounded-3xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  />
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t(
                      'admin.recognition_operator_notes_help',
                      {},
                      'Write why: why this row is candidate, why it stays out of platform serving, what intelligence is weak, or what should be checked next.'
                    )}
                  </p>
                </label>
              </div>

              {saveMessage ? (
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200">
                  {saveMessage}
                </div>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void saveAnnotation()}
                  disabled={isSaving}
                  className="btn btn-primary disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSaving ? t('common.saving', {}, 'Saving...') : t('common.save_changes', {}, 'Save Changes')}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    window.open(
                      getHostedModelsHref(selectedModel.provider_id, selectedModel.model_id),
                      '_blank',
                      'noopener,noreferrer'
                    )
                  }
                  className="btn btn-secondary"
                >
                    {t('admin.open_hosted_models', {}, 'Review platform models')}
                  </button>
              </div>
            </div>
          ) : (
            <div className="mt-6 rounded-3xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-8 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-400">
              {t('admin.select_model_prompt', {}, 'Select a model to inspect details.')}
            </div>
          )}
        </BackofficeStackCard>
      </div>
    </BackofficePageStack>
  );
}

export default function RecognitionPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <RecognitionPageContent />
    </Suspense>
  );
}
