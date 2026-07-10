import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { ProviderReferenceLinks } from '@/components/admin/ProviderReferenceLinks';
import { formatDate } from '@/lib/utils';

export type ResourceStatus = 'ready' | 'missing_secret' | 'missing_provider' | 'disabled' | string;
export type ConnectionStatusFilter = 'all' | 'ready' | 'missing_secret' | 'disabled';
export type CapabilityProviderCategory = 'search' | 'image' | 'vector';
export type CapabilityProviderCategoryFilter = 'all' | CapabilityProviderCategory;

export type SupplierConnection = {
  connection_id: string;
  provider_id: string;
  display_name: string;
  kind: string;
  enabled: boolean;
  configured: boolean;
  status: ResourceStatus;
  base_url: string;
  note: string;
  priority: number;
  capability_ids: string[];
  runtime_profile_ids: string[];
  model_ids?: string[];
  last_tested_at?: string;
  last_error_code?: string;
  last_error_message?: string;
  detail_href?: string;
  managed_by?: string;
  metadata?: Record<string, any>;
};

export type ProviderConnectionTestResult = {
  connection_id: string;
  provider_id: string;
  kind: string;
  status: ResourceStatus;
  stage: string;
  ok: boolean;
  error_code: string;
  message: string;
  tested_at: string;
  catalog?: {
    provider_id?: string;
    display_name?: string;
    adapter_type?: string;
    model_count?: number;
    sample_model_ids?: string[];
  };
  probe?: {
    provider_id?: string;
    result_count?: number;
    latency_ms?: number;
    write_posture?: string;
    direct_wordpress_write?: boolean;
  };
};

type Translate = (
  key: string,
  fallback: string,
  variables?: Record<string, string>
) => string;

type ReferenceLinkItem = {
  key: string;
  labelKey: string;
  fallback: string;
  href: string;
};

const QUIET_STATUS_BADGE_CLASS =
  'bg-slate-50 px-2 py-0.5 text-xs normal-case tracking-normal text-slate-600 dark:bg-slate-900 dark:text-slate-300';

const TABLE_ACTION_BUTTON_CLASS =
  'rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700';

const TABLE_DELETE_BUTTON_CLASS =
  'rounded-full border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:border-rose-300 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-900 dark:bg-slate-950 dark:text-rose-300 dark:hover:border-rose-800 dark:hover:bg-rose-950/20';

const TABLE_CONFIRM_DELETE_BUTTON_CLASS =
  'rounded-full border border-rose-300 bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-800 transition hover:border-rose-400 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200 dark:hover:border-rose-700 dark:hover:bg-rose-950/50';

function statusTone(status: ResourceStatus): 'success' | 'warning' | 'disabled' | 'info' {
  if (status === 'ready' || status === 'healthy') return 'success';
  if (status === 'missing_secret' || status === 'missing_provider' || status === 'saved_credential_unreadable' || status === 'degraded') return 'warning';
  if (status === 'disabled') return 'disabled';
  return 'info';
}

function resourceStatusLabel(status: ResourceStatus, translate: Translate): string {
  const labels: Record<string, string> = {
    ready: translate('status_ready_label', 'Ready'),
    missing_secret: translate('status_missing_secret_label', 'Missing secret'),
    missing_provider: translate('status_missing_provider_label', 'Missing provider'),
    saved_credential_unreadable: translate('status_saved_credential_unreadable_label', 'Credential must be saved again'),
    disabled: translate('status_disabled_label', 'Disabled'),
    healthy: translate('status_healthy_label', 'Healthy'),
    degraded: translate('status_degraded_label', 'Degraded'),
    error: translate('status_error_label', 'Error'),
    warning: translate('status_warning_label', 'Warning'),
    info: translate('status_info_label', 'Info'),
    not_observed: translate('status_not_observed', 'Not observed'),
  };
  return labels[status] || status;
}

function connectionErrorLabel(errorCode: string, translate: Translate): string {
  const labels: Record<string, string> = {
    'provider_connection.unsupported_provider_kind': translate(
      'provider_error_unsupported_kind',
      'This connection type cannot be tested automatically.'
    ),
  };
  return labels[errorCode] || translate(
    'provider_last_test_failed',
    'The last test failed. Open configuration, verify the credential, and retry.'
  );
}

function StatusFilter({
  value,
  onChange,
  translate,
  className = '',
}: {
  value: ConnectionStatusFilter;
  onChange: (value: ConnectionStatusFilter) => void;
  translate: Translate;
  className?: string;
}) {
  return (
    <select
      className={`h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 ${className}`.trim()}
      value={value}
      onChange={(event) => onChange(event.target.value as ConnectionStatusFilter)}
      aria-label={translate('status_filter_label', 'Status')}
    >
      <option value="all">{translate('filter_all_statuses', 'All statuses')}</option>
      <option value="ready">{translate('filter_ready', 'Ready')}</option>
      <option value="missing_secret">{translate('filter_missing_secret', 'Missing secret')}</option>
      <option value="disabled">{translate('filter_disabled', 'Disabled')}</option>
    </select>
  );
}

function ConnectionIssue({ connection, translate }: { connection: SupplierConnection; translate: Translate }) {
  if (connection.enabled && connection.configured) return null;
  if (connection.status === 'saved_credential_unreadable') {
    return (
      <div className="mt-2 text-xs font-medium leading-5 text-amber-700 dark:text-amber-300">
        {translate('provider_issue_credential_unreadable', 'The saved credential cannot be read. Enter and save it again.')}
      </div>
    );
  }
  return (
    <div className="mt-2 text-xs font-medium leading-5">
      {!connection.enabled ? (
        <span className="text-slate-500 dark:text-slate-400">
          {translate('provider_issue_runtime_disabled', 'Runtime calls are disabled')}
        </span>
      ) : null}
      {!connection.enabled && !connection.configured ? (
        <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
      ) : null}
      {!connection.configured ? (
        <span className="text-amber-700 dark:text-amber-300">
          {translate('provider_issue_missing_credential', 'Provider credential is not configured')}
        </span>
      ) : null}
    </div>
  );
}

type SharedTableProps = {
  statusFilter: ConnectionStatusFilter;
  onStatusFilterChange: (value: ConnectionStatusFilter) => void;
  testResults: Record<string, ProviderConnectionTestResult>;
  deletingConnectionId: string;
  confirmingDeleteConnectionId: string;
  onDelete: (connection: SupplierConnection) => void;
  onRequestDelete: (connectionId: string) => void;
  onCancelDelete: () => void;
  providerTestStageLabel: (stage: string) => string;
  providerTestMessage: (result: ProviderConnectionTestResult) => string;
  translate: Translate;
};

type ModelSupplierTableProps = SharedTableProps & {
  connections: SupplierConnection[];
  providerKindLabel: (kind: string) => string;
  referenceLinksForConnection: (connection: SupplierConnection) => ReferenceLinkItem[];
  onConfigure: (connection: SupplierConnection) => void;
};

export function ModelSupplierTable({
  connections,
  statusFilter,
  onStatusFilterChange,
  testResults,
  deletingConnectionId,
  confirmingDeleteConnectionId,
  providerKindLabel,
  providerTestStageLabel,
  providerTestMessage,
  referenceLinksForConnection,
  onConfigure,
  onDelete,
  onRequestDelete,
  onCancelDelete,
  translate,
}: ModelSupplierTableProps) {
  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <div className="overflow-x-auto">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
            <tr>
              <th className="px-4 py-3">
                <StatusFilter value={statusFilter} onChange={onStatusFilterChange} translate={translate} />
              </th>
              <th className="px-4 py-3">{translate('column_provider', 'Provider')}</th>
              <th className="px-4 py-3">{translate('column_enabled_models', 'Runtime allowlist')}</th>
              <th className="px-4 py-3">{translate('last_test', 'Last test')}</th>
              <th className="w-44 px-4 py-3 text-center">{translate('column_actions', 'Actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {connections.map((connection) => {
              const testResult = testResults[connection.connection_id];
              const isDeleting = deletingConnectionId === connection.connection_id;
              const isConfirmingDelete = confirmingDeleteConnectionId === connection.connection_id;
              const modelIds = connection.model_ids || [];
              const providerLinkItems = referenceLinksForConnection(connection);
              return (
                <tr key={connection.connection_id} className="align-top">
                  <td className="px-4 py-4">
                    <BackofficeStatusBadge
                      label={resourceStatusLabel(connection.status, translate)}
                      status={statusTone(connection.status)}
                      className={connection.status === 'ready' ? QUIET_STATUS_BADGE_CLASS : undefined}
                    />
                  </td>
                  <td className="px-4 py-4">
                    <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {connection.provider_id} · {providerKindLabel(connection.kind)}
                    </div>
                    {connection.note ? <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{connection.note}</div> : null}
                    <ProviderReferenceLinks
                      items={providerLinkItems}
                      label={translate('provider_links_title', 'Reference links')}
                      translate={translate}
                      variant="inline"
                    />
                    <ConnectionIssue connection={connection} translate={translate} />
                  </td>
                  <td className="px-4 py-4 text-slate-600 dark:text-slate-300">
                    <div className="font-semibold text-slate-900 dark:text-white">
                      {modelIds.length
                        ? translate('model_catalog_enabled_count_short', '{{count}} models', { count: String(modelIds.length) })
                        : translate('model_catalog_none_enabled_short', '0 models')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {translate('model_catalog_allowlist_short_hint', 'Only these models can be selected by ability routes.')}
                    </div>
                  </td>
                  <td className="max-w-[18rem] px-4 py-4 text-slate-600 dark:text-slate-300">
                    {testResult ? (
                      <div className="grid gap-1">
                        <div className="flex items-center gap-2">
                          <BackofficeStatusBadge
                            label={resourceStatusLabel(testResult.status, translate)}
                            status={testResult.ok ? 'success' : 'warning'}
                          />
                          <span className="text-xs text-slate-500 dark:text-slate-400">{providerTestStageLabel(testResult.stage)}</span>
                        </div>
                        <div className="text-xs leading-5">{providerTestMessage(testResult)}</div>
                        {testResult.catalog?.model_count ? (
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {translate('catalog_models', 'Catalog models')}: {testResult.catalog.model_count} · {(testResult.catalog.sample_model_ids || []).join(', ')}
                          </div>
                        ) : null}
                      </div>
                    ) : connection.last_tested_at ? (
                      <div className="grid gap-1">
                        <div className="text-xs text-slate-500 dark:text-slate-400">{formatDate(connection.last_tested_at)}</div>
                        {connection.last_error_code ? (
                          <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">
                            {connectionErrorLabel(connection.last_error_code, translate)}
                          </div>
                        ) : null}
                      </div>
                    ) : <span className="text-slate-400 dark:text-slate-500">-</span>}
                  </td>
                  <td className="w-44 px-4 py-4 text-center">
                    <div className="flex flex-wrap items-center justify-center gap-3">
                      {isConfirmingDelete ? (
                        <>
                          <button type="button" className={TABLE_CONFIRM_DELETE_BUTTON_CLASS} disabled={isDeleting} onClick={() => onDelete(connection)}>
                            {isDeleting ? translate('deleting', 'Deleting...') : translate('action_confirm_delete', 'Confirm delete')}
                          </button>
                          <button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={isDeleting} onClick={onCancelDelete}>
                            {translate('action_cancel', 'Cancel')}
                          </button>
                        </>
                      ) : (
                        <>
                          <button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={isDeleting} onClick={() => onConfigure(connection)}>
                            {translate('action_configure', 'Configure')}
                          </button>
                          {connection.managed_by === 'cloud_provider_connections' ? (
                            <button type="button" className={TABLE_DELETE_BUTTON_CLASS} disabled={isDeleting} onClick={() => onRequestDelete(connection.connection_id)}>
                              {translate('action_delete', 'Delete')}
                            </button>
                          ) : null}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {connections.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                  {translate('ai_suppliers_empty', 'No model suppliers match the current filters.')}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type CapabilitySupplierTableProps = SharedTableProps & {
  connections: SupplierConnection[];
  connectionsByCategory: Record<CapabilityProviderCategory, SupplierConnection[]>;
  categoryFilter: CapabilityProviderCategoryFilter;
  onCategoryFilterChange: (value: CapabilityProviderCategoryFilter) => void;
  channelCounts: Map<string, number>;
  testingConnectionId: string;
  categoryForConnection: (connection: SupplierConnection) => CapabilityProviderCategory;
  categoryLabel: (category: CapabilityProviderCategory) => string;
  purposeLabel: (connection: SupplierConnection) => string;
  onTest: (connectionId: string) => void;
  onConfigure: (connection: SupplierConnection) => void;
};

export function CapabilitySupplierTable({
  connections,
  connectionsByCategory,
  categoryFilter,
  onCategoryFilterChange,
  statusFilter,
  onStatusFilterChange,
  testResults,
  channelCounts,
  testingConnectionId,
  deletingConnectionId,
  confirmingDeleteConnectionId,
  categoryForConnection,
  categoryLabel,
  purposeLabel,
  providerTestStageLabel,
  providerTestMessage,
  onTest,
  onConfigure,
  onDelete,
  onRequestDelete,
  onCancelDelete,
  translate,
}: CapabilitySupplierTableProps) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <div className="overflow-x-auto">
        <table className="min-w-[960px] w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
            <tr>
              <th className="px-4 py-3">{translate('column_provider', 'Provider')}</th>
              <th className="px-4 py-3">
                <select
                  className="h-8 w-36 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                  value={categoryFilter}
                  onChange={(event) => onCategoryFilterChange(event.target.value as CapabilityProviderCategoryFilter)}
                  aria-label={translate('capability_category_filter', 'Capability category')}
                >
                  <option value="all">{translate('filter_all_categories', 'All categories')}</option>
                  {(['search', 'image', 'vector'] as CapabilityProviderCategory[]).map((category) => (
                    <option key={category} value={category}>{categoryLabel(category)} · {connectionsByCategory[category].length}</option>
                  ))}
                </select>
              </th>
              <th className="px-4 py-3">
                <StatusFilter value={statusFilter} onChange={onStatusFilterChange} translate={translate} className="w-36" />
              </th>
              <th className="px-4 py-3">{translate('column_connection', 'Connection')}</th>
              <th className="px-4 py-3">{translate('last_test', 'Last test')}</th>
              <th className="w-52 px-4 py-3 text-center">{translate('column_actions', 'Actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {connections.map((connection) => {
              const category = categoryForConnection(connection);
              const testResult = testResults[connection.connection_id];
              const isTesting = testingConnectionId === connection.connection_id;
              const isDeleting = deletingConnectionId === connection.connection_id;
              const isConfirmingDelete = confirmingDeleteConnectionId === connection.connection_id;
              const canTestConnection = connection.managed_by === 'cloud_provider_connections';
              const channelCount = channelCounts.get(`${connection.kind}:${connection.provider_id}`) || 0;
              const showPriority = channelCount > 1 || Number(connection.priority ?? 100) !== 100;
              return (
                <tr key={connection.connection_id} className="align-top">
                  <td className="px-4 py-4 align-middle">
                    <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{purposeLabel(connection)}</div>
                  </td>
                  <td className="px-4 py-4 align-middle text-xs font-semibold text-slate-600 dark:text-slate-300">{categoryLabel(category)}</td>
                  <td className="px-4 py-4 align-middle">
                    <BackofficeStatusBadge
                      label={resourceStatusLabel(connection.status, translate)}
                      status={statusTone(connection.status)}
                      className={connection.status === 'ready' ? QUIET_STATUS_BADGE_CLASS : undefined}
                    />
                  </td>
                  <td className="px-4 py-4 align-middle">
                    <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                      <span>{connection.enabled ? translate('field_enabled', 'Enabled') : translate('status_disabled_label', 'Disabled')}</span>
                      <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                      <span className={connection.configured ? '' : 'font-semibold text-amber-700 dark:text-amber-300'}>
                        {connection.configured ? translate('status_configured_label', 'Configured') : translate('status_missing_secret_label', 'Missing secret')}
                      </span>
                      {showPriority ? <><span className="mx-1 text-slate-300 dark:text-slate-700">·</span><span>{translate('channel_priority_summary', 'Priority {{priority}}', { priority: String(connection.priority ?? 100) })}</span></> : null}
                      {connection.note ? <div className="mt-1 max-w-[16rem] truncate text-slate-400 dark:text-slate-500">{connection.note}</div> : null}
                    </div>
                  </td>
                  <td className="max-w-[18rem] px-4 py-4 align-middle text-slate-600 dark:text-slate-300">
                    {testResult ? (
                      <div className="grid gap-1">
                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                          <span className={`h-1.5 w-1.5 rounded-full ${testResult.ok ? 'bg-emerald-500' : 'bg-amber-500'}`} aria-hidden="true" />
                          <span className={testResult.ok ? 'font-semibold text-slate-700 dark:text-slate-200' : 'font-semibold text-amber-700 dark:text-amber-300'}>
                            {testResult.ok ? translate('test_passed', 'Passed') : resourceStatusLabel(testResult.status, translate)}
                          </span>
                          <span className="text-slate-300 dark:text-slate-700">·</span>
                          <span className="text-slate-500 dark:text-slate-400">{formatDate(testResult.tested_at)}</span>
                          <span className="text-slate-300 dark:text-slate-700">·</span>
                          <span className="text-slate-500 dark:text-slate-400">{providerTestStageLabel(testResult.stage)}</span>
                        </div>
                        {!testResult.ok ? <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">{providerTestMessage(testResult)}</div> : null}
                      </div>
                    ) : connection.last_tested_at ? (
                      connection.last_error_code ? (
                        <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">
                          {translate('test_failed', 'Failed')} · {formatDate(connection.last_tested_at)} · {connection.last_error_code}
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                          <span className="font-semibold text-slate-700 dark:text-slate-200">{translate('test_passed', 'Passed')}</span>
                          <span className="text-slate-300 dark:text-slate-700">·</span>
                          <span>{formatDate(connection.last_tested_at)}</span>
                        </div>
                      )
                    ) : <span className="text-slate-400 dark:text-slate-500">-</span>}
                  </td>
                  <td className="w-52 px-4 py-4 text-center align-middle">
                    <div className="flex flex-wrap items-center justify-center gap-3">
                      {isConfirmingDelete ? (
                        <>
                          <button type="button" className={TABLE_CONFIRM_DELETE_BUTTON_CLASS} disabled={isDeleting} onClick={() => onDelete(connection)}>
                            {isDeleting ? translate('deleting', 'Deleting...') : translate('action_confirm_delete', 'Confirm delete')}
                          </button>
                          <button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={isDeleting} onClick={onCancelDelete}>{translate('action_cancel', 'Cancel')}</button>
                        </>
                      ) : (
                        <>
                          {canTestConnection ? (
                            <button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={isTesting || isDeleting} onClick={() => onTest(connection.connection_id)}>
                              {isTesting ? translate('testing', 'Testing...') : translate('action_test', 'Test')}
                            </button>
                          ) : null}
                          <button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={isDeleting} onClick={() => onConfigure(connection)}>{translate('action_configure', 'Configure')}</button>
                          {connection.managed_by === 'cloud_provider_connections' ? (
                            <button type="button" className={TABLE_DELETE_BUTTON_CLASS} disabled={isDeleting} onClick={() => onRequestDelete(connection.connection_id)}>{translate('action_delete', 'Delete')}</button>
                          ) : null}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {connections.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">{translate('capability_category_empty', 'No suppliers match the current category and filters.')}</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
