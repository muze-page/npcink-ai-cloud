export type OperatorSeverity = 'watch' | 'warn' | 'action-needed';

export type RuntimeSummarySignalInput = {
  queuedRuns: number;
  runningRuns: number;
  callbackFailed: number;
  callbackPending: number;
  guardEvents: number;
};

export type OperatorRuntimeSignal = {
  key: 'queued' | 'running' | 'callback' | 'guard';
  label: string;
  scope: string;
  value: number;
  severity: OperatorSeverity;
  reason: string;
  issueClass: string;
};

export type OperatorWatchItem = {
  title: string;
  scope: string;
  severity: OperatorSeverity;
  reason: string;
  value: string;
};

type OperatorWatchItemDraft = OperatorWatchItem & {
  priority: number;
};

type BuildRuntimeSignalLabels = {
  queuedRuns: string;
  runningRuns: string;
  callbackFailed: string;
  guardEvents: string;
};

type BuildRuntimeSignalCopy = {
  queuedElevated: string;
  queuedWatch: string;
  queuedNominal: string;
  runningElevated: string;
  runningWatch: string;
  runningNominal: string;
  callbackFailed: string;
  callbackPending: string;
  callbackNominal: string;
  guardHot: string;
  guardWatch: string;
  guardNominal: string;
};

type BuildWatchItemInputs = {
  runtimeSummary: RuntimeSummarySignalInput;
  expiringSubscriptionsIn7Days: number;
  attentionSubscriptionsCount: number;
  firstAttentionReason: string;
  hostedModelGovernance: {
    status: string;
    alertCount: number;
    firstAlertTitle: string;
    firstAlertSummary: string;
    summary: string;
  };
  formatValue: (value: number) => string;
  copy: {
    callbackTitle: string;
    callbackReason: string;
    guardTitle: string;
    guardReason: string;
    expiryTitle: string;
    expiryReason: string;
    attentionTitle: string;
    attentionFallbackReason: string;
    hostedTitle: string;
    hostedReason: string;
  };
};

/**
 * Frontend-only operator framing.
 *
 * These thresholds, severity bands, and reason strings are intentionally kept
 * on the frontend side so admin pages can present a stable operator console
 * without implying backend/runtime contract truth.
 */
export function buildAdminRuntimeSignals(
  runtimeSummary: RuntimeSummarySignalInput,
  labels: BuildRuntimeSignalLabels,
  copy: BuildRuntimeSignalCopy
): OperatorRuntimeSignal[] {
  return [
    {
      key: 'queued',
      label: labels.queuedRuns,
      scope: 'runtime.queue',
      value: runtimeSummary.queuedRuns,
      severity: runtimeSummary.queuedRuns >= 20 ? 'warn' : 'watch',
      reason:
        runtimeSummary.queuedRuns >= 20
          ? copy.queuedElevated
          : runtimeSummary.queuedRuns > 0
            ? copy.queuedWatch
            : copy.queuedNominal,
      issueClass:
        runtimeSummary.queuedRuns >= 20
          ? 'queue_backlog'
          : runtimeSummary.queuedRuns > 0
            ? 'queue_watch'
            : 'nominal',
    },
    {
      key: 'running',
      label: labels.runningRuns,
      scope: 'runtime.worker',
      value: runtimeSummary.runningRuns,
      severity: runtimeSummary.runningRuns >= 12 ? 'warn' : 'watch',
      reason:
        runtimeSummary.runningRuns >= 12
          ? copy.runningElevated
          : runtimeSummary.runningRuns > 0
            ? copy.runningWatch
            : copy.runningNominal,
      issueClass:
        runtimeSummary.runningRuns >= 12
          ? 'worker_pressure'
          : runtimeSummary.runningRuns > 0
            ? 'worker_watch'
            : 'nominal',
    },
    {
      key: 'callback',
      label: labels.callbackFailed,
      scope: 'runtime.callback',
      value: runtimeSummary.callbackFailed,
      severity:
        runtimeSummary.callbackFailed > 0
          ? 'action-needed'
          : runtimeSummary.callbackPending > 0
            ? 'warn'
            : 'watch',
      reason:
        runtimeSummary.callbackFailed > 0
          ? copy.callbackFailed
          : runtimeSummary.callbackPending > 0
            ? copy.callbackPending
            : copy.callbackNominal,
      issueClass:
        runtimeSummary.callbackFailed > 0
          ? 'callback_failed'
          : runtimeSummary.callbackPending > 0
            ? 'callback_pending'
            : 'nominal',
    },
    {
      key: 'guard',
      label: labels.guardEvents,
      scope: 'request.guard',
      value: runtimeSummary.guardEvents,
      severity:
        runtimeSummary.guardEvents >= 25
          ? 'action-needed'
          : runtimeSummary.guardEvents > 0
            ? 'warn'
            : 'watch',
      reason:
        runtimeSummary.guardEvents >= 25
          ? copy.guardHot
          : runtimeSummary.guardEvents > 0
            ? copy.guardWatch
            : copy.guardNominal,
      issueClass:
        runtimeSummary.guardEvents >= 25
          ? 'guard_hot'
          : runtimeSummary.guardEvents > 0
            ? 'guard_watch'
            : 'nominal',
    },
  ];
}

export function buildAdminOperatorWatchItems(
  inputs: BuildWatchItemInputs
): OperatorWatchItem[] {
  const items: OperatorWatchItemDraft[] = [];

  if (inputs.runtimeSummary.callbackFailed > 0) {
    items.push({
      title: inputs.copy.callbackTitle,
      scope: 'runtime.callback',
      severity: 'action-needed',
      reason: inputs.copy.callbackReason,
      value: inputs.formatValue(inputs.runtimeSummary.callbackFailed),
      priority: 10,
    });
  }

  if (inputs.runtimeSummary.guardEvents > 0) {
    items.push({
      title: inputs.copy.guardTitle,
      scope: 'request.guard',
      severity: inputs.runtimeSummary.guardEvents >= 25 ? 'action-needed' : 'warn',
      reason: inputs.copy.guardReason,
      value: inputs.formatValue(inputs.runtimeSummary.guardEvents),
      priority: inputs.runtimeSummary.guardEvents >= 25 ? 20 : 40,
    });
  }

  if (inputs.expiringSubscriptionsIn7Days > 0) {
    items.push({
      title: inputs.copy.expiryTitle,
      scope: 'commercial.subscription',
      severity: 'warn',
      reason: inputs.copy.expiryReason,
      value: inputs.formatValue(inputs.expiringSubscriptionsIn7Days),
      priority: 50,
    });
  }

  if (inputs.attentionSubscriptionsCount > 0) {
    items.push({
      title: inputs.copy.attentionTitle,
      scope: 'commercial.subscription',
      severity: 'action-needed',
      reason:
        inputs.firstAttentionReason ||
        inputs.copy.attentionFallbackReason,
      value: inputs.formatValue(inputs.attentionSubscriptionsCount),
      priority: 30,
    });
  }

  if (inputs.hostedModelGovernance.status === 'error' || inputs.hostedModelGovernance.status === 'warning') {
    const severity = inputs.hostedModelGovernance.status === 'error' ? 'action-needed' : 'warn';
    items.push({
      title: inputs.hostedModelGovernance.firstAlertTitle || inputs.copy.hostedTitle,
      scope: 'runtime.telemetry_coverage',
      severity,
      reason:
        inputs.hostedModelGovernance.firstAlertSummary ||
        inputs.hostedModelGovernance.summary ||
        inputs.copy.hostedReason,
      value: inputs.formatValue(Math.max(inputs.hostedModelGovernance.alertCount, 1)),
      priority: severity === 'action-needed' ? 15 : 35,
    });
  }

  return items
    .sort((left, right) => left.priority - right.priority)
    .map((item) => ({
      title: item.title,
      scope: item.scope,
      severity: item.severity,
      reason: item.reason,
      value: item.value,
    }));
}

export function operatorSeverityClasses(severity: OperatorSeverity): string {
  switch (severity) {
    case 'action-needed':
      return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200';
    case 'warn':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200';
    default:
      return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/50 dark:bg-blue-950/20 dark:text-blue-200';
  }
}
