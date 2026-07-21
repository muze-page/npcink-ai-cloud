import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { ProviderReferenceLinks } from '@/components/admin/ProviderReferenceLinks';
import { formatDate } from '@/lib/utils';

export type ResourceStatus = 'ready' | 'missing_secret' | 'missing_provider' | 'disabled' | string;
export type ConnectionStatusFilter = 'all' | 'ready' | 'missing_secret' | 'disabled';

export type SupplierConnection = {
  connection_id: string;
  provider_id: string;
  display_name: string;
  kind: string;
  enabled: boolean;
  configured: boolean;
  status: ResourceStatus;
  base_url: string;
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
  selectedConnectionId: string;
  onSelectConnection: (connectionId: string) => void;
  testResults: Record<string, ProviderConnectionTestResult>;
  testingConnectionId: string;
  deletingConnectionId: string;
  confirmingDeleteConnectionId: string;
  onDelete: (connection: SupplierConnection) => void;
  onRequestDelete: (connectionId: string) => void;
  onCancelDelete: () => void;
  providerTestStageLabel: (stage: string) => string;
  providerTestMessage: (result: ProviderConnectionTestResult) => string;
  onTest: (connectionId: string) => void;
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
  selectedConnectionId,
  onSelectConnection,
  testResults,
  testingConnectionId,
  deletingConnectionId,
  confirmingDeleteConnectionId,
  providerKindLabel,
  providerTestStageLabel,
  providerTestMessage,
  referenceLinksForConnection,
  onConfigure,
  onTest,
  onDelete,
  onRequestDelete,
  onCancelDelete,
  translate,
}: ModelSupplierTableProps) {
  const selectedConnection = connections.find((connection) => connection.connection_id === selectedConnectionId) || connections[0] || null;
  const selectedTestResult = selectedConnection ? testResults[selectedConnection.connection_id] : undefined;
  const selectedProviderLinks = selectedConnection ? referenceLinksForConnection(selectedConnection) : [];
  const selectedIsTesting = selectedConnection ? testingConnectionId === selectedConnection.connection_id : false;
  const selectedIsDeleting = selectedConnection ? deletingConnectionId === selectedConnection.connection_id : false;
  const selectedIsConfirmingDelete = selectedConnection ? confirmingDeleteConnectionId === selectedConnection.connection_id : false;

  return (
    <div data-ui="model-supplier-directory" className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
          <div>
            <h2 className="text-sm font-semibold text-slate-950 dark:text-white">{translate('model_directory_title', 'Model supplier queue')}</h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{translate('directory_result_count', '{{count}} suppliers', { count: String(connections.length) })}</p>
          </div>
          <StatusFilter value={statusFilter} onChange={onStatusFilterChange} translate={translate} />
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {connections.map((connection) => {
            const testResult = testResults[connection.connection_id];
            const modelCount = connection.model_ids?.length || 0;
            const isSelected = selectedConnection?.connection_id === connection.connection_id;
            return (
              <button
                key={connection.connection_id}
                type="button"
                data-connection-id={connection.connection_id}
                aria-pressed={isSelected}
                className={`grid w-full gap-3 px-4 py-3 text-left transition sm:grid-cols-[minmax(0,1fr)_8rem_8rem] sm:items-center ${isSelected ? 'bg-blue-50/80 dark:bg-blue-950/20' : 'hover:bg-slate-50 dark:hover:bg-slate-900/40'}`}
                onClick={() => onSelectConnection(connection.connection_id)}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-semibold text-slate-950 dark:text-white">{connection.display_name}</span>
                    <BackofficeStatusBadge label={resourceStatusLabel(connection.status, translate)} status={statusTone(connection.status)} className={connection.status === 'ready' ? QUIET_STATUS_BADGE_CLASS : undefined} />
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{connection.provider_id} · {providerKindLabel(connection.kind)}</p>
                  <ConnectionIssue connection={connection} translate={translate} />
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">{translate('model_catalog_enabled_count_short', '{{count}} models', { count: String(modelCount) })}</span>
                  <span className="mt-0.5 block sm:hidden">{translate('column_enabled_models', 'Runtime allowlist')}</span>
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">{testResult ? (testResult.ok ? translate('test_passed', 'Passed') : resourceStatusLabel(testResult.status, translate)) : connection.last_tested_at ? formatDate(connection.last_tested_at) : '-'}</span>
                  <span className="mt-0.5 block sm:hidden">{translate('last_test', 'Last test')}</span>
                </div>
              </button>
            );
          })}
          {connections.length === 0 ? <p className="px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400">{translate('ai_suppliers_empty', 'No model suppliers match the current filters.')}</p> : null}
        </div>
      </section>

      <aside data-ui="supplier-inspector" className="xl:sticky xl:top-24 xl:self-start">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{translate('inspector_eyebrow', 'Inspector')}</p>
          {selectedConnection ? (
            <div className="mt-3 space-y-4">
              <div><h2 className="text-lg font-semibold text-slate-950 dark:text-white">{selectedConnection.display_name}</h2><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{selectedConnection.provider_id} · {providerKindLabel(selectedConnection.kind)}</p></div>
              <dl className="grid gap-2 text-sm">
                {[
                  [translate('status_filter_label', 'Status'), resourceStatusLabel(selectedConnection.status, translate)],
                  [translate('field_enabled', 'Enabled'), selectedConnection.enabled ? translate('status_enabled_label', 'Enabled') : translate('status_disabled_label', 'Disabled')],
                  [translate('column_enabled_models', 'Runtime allowlist'), translate('model_catalog_enabled_count_short', '{{count}} models', { count: String(selectedConnection.model_ids?.length || 0) })],
                  [translate('last_test', 'Last test'), selectedConnection.last_tested_at ? formatDate(selectedConnection.last_tested_at) : '-'],
                ].map(([label, value]) => <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-0 dark:border-slate-800"><dt className="text-slate-500 dark:text-slate-400">{label}</dt><dd className="text-right font-semibold text-slate-900 dark:text-white">{value}</dd></div>)}
              </dl>
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{translate('model_catalog_allowlist_short_hint', 'Only these models can be selected by ability routes.')}</p>
              {selectedTestResult && !selectedTestResult.ok ? <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-200">{providerTestStageLabel(selectedTestResult.stage)} · {providerTestMessage(selectedTestResult)}</p> : selectedTestResult?.ok ? <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">{translate('test_result_passed_inline', 'Test passed')} · {providerTestMessage(selectedTestResult)}</p> : selectedConnection.last_error_code ? <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">{connectionErrorLabel(selectedConnection.last_error_code, translate)}</p> : null}
              <ProviderReferenceLinks items={selectedProviderLinks} label={translate('provider_links_title', 'Reference links')} translate={translate} variant="inline" />
              <div className="flex flex-wrap gap-2">
                {selectedConnection.managed_by === 'cloud_provider_connections' ? <button type="button" className="btn btn-secondary btn-sm" disabled={selectedIsTesting || selectedIsDeleting} onClick={() => onTest(selectedConnection.connection_id)}>{selectedIsTesting ? translate('testing', 'Testing...') : translate('action_test', 'Test')}</button> : null}
                <button type="button" className="btn btn-primary btn-sm" disabled={selectedIsDeleting} onClick={() => onConfigure(selectedConnection)}>{translate('action_configure', 'Configure')}</button>
                {selectedConnection.managed_by === 'cloud_provider_connections' ? selectedIsConfirmingDelete ? <><button type="button" className={TABLE_CONFIRM_DELETE_BUTTON_CLASS} disabled={selectedIsDeleting} onClick={() => onDelete(selectedConnection)}>{selectedIsDeleting ? translate('deleting', 'Deleting...') : translate('action_confirm_delete', 'Confirm delete')}</button><button type="button" className={TABLE_ACTION_BUTTON_CLASS} disabled={selectedIsDeleting} onClick={onCancelDelete}>{translate('action_cancel', 'Cancel')}</button></> : <button type="button" className={TABLE_DELETE_BUTTON_CLASS} disabled={selectedIsDeleting} onClick={() => onRequestDelete(selectedConnection.connection_id)}>{translate('action_delete', 'Delete')}</button> : null}
              </div>
              {selectedIsConfirmingDelete ? <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">{translate('delete_confirmation_notice', 'Deleting {{name}} removes this runtime connection. Existing model bindings may stop resolving.', { name: selectedConnection.display_name })}</p> : null}
              <p className="border-t border-slate-200 pt-3 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">{translate('inspector_boundary', 'This inspector reads Cloud runtime provider detail. Model routing and WordPress control remain in their owning surfaces.')}</p>
            </div>
          ) : <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">{translate('inspector_empty', 'No supplier is visible in this view.')}</p>}
        </div>
      </aside>
    </div>
  );
}
