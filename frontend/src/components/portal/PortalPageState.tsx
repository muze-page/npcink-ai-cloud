'use client';

import type { ReactNode } from 'react';
import { useLocale } from '@/contexts/LocaleContext';

type PortalLoadingStateProps = {
  message: string;
};

type PortalSignedOutStateProps = {
  title: string;
  description: string;
  actionLabel: string;
  actionHref?: string;
};

type PortalErrorStateProps = {
  title: string;
  description: string;
  retryLabel: string;
  onRetry: () => void;
};

type PortalEmptyStateProps = {
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  actionButton?: ReactNode;
  diagnosticCode?: string;
};

export function PortalLoadingState({ message }: PortalLoadingStateProps) {
  return (
    <div className="min-h-[60vh] py-6" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{message}</span>
      <div className="space-y-5 motion-safe:animate-pulse" aria-hidden="true">
        <div className="h-8 w-44 rounded-xl bg-slate-200/80 dark:bg-slate-800" />
        <div className="grid gap-3 md:grid-cols-3">
          <div className="h-28 rounded-2xl bg-slate-200/70 dark:bg-slate-800/80" />
          <div className="h-28 rounded-2xl bg-slate-200/70 dark:bg-slate-800/80" />
          <div className="h-28 rounded-2xl bg-slate-200/70 dark:bg-slate-800/80" />
        </div>
        <div className="h-64 rounded-2xl bg-slate-200/60 dark:bg-slate-800/70" />
      </div>
    </div>
  );
}

export function PortalSignedOutState({
  title,
  description,
  actionLabel,
  actionHref = '/portal/login',
}: PortalSignedOutStateProps) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="max-w-md text-center">
        <h2 className="mb-4 text-2xl font-bold">{title}</h2>
        <p className="mb-6 text-gray-600 dark:text-gray-400">{description}</p>
        <a href={actionHref} className="btn btn-primary">
          {actionLabel}
        </a>
      </div>
    </div>
  );
}

export function PortalErrorState({
  title,
  description,
  retryLabel,
  onRetry,
}: PortalErrorStateProps) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="max-w-md text-center">
        <h2 className="mb-4 text-2xl font-bold">{title}</h2>
        <p className="mb-6 text-gray-600 dark:text-gray-400">{description}</p>
        <button onClick={onRetry} className="btn btn-primary">
          {retryLabel}
        </button>
      </div>
    </div>
  );
}

export function PortalEmptyState({
  title,
  description,
  actionLabel,
  actionHref,
  actionButton,
  diagnosticCode,
}: PortalEmptyStateProps) {
  const { t } = useLocale();
  return (
    <div className="flex min-h-[16rem] items-center justify-center rounded-[1.4rem] border border-dashed border-slate-300/80 bg-slate-50/70 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-950/30">
      <div className="max-w-lg">
        <h2 className="text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p>
        {actionButton ? (
          <div className="mt-5">{actionButton}</div>
        ) : actionLabel && actionHref ? (
          <a href={actionHref} className="btn btn-primary mt-5">
            {actionLabel}
          </a>
        ) : null}
        {diagnosticCode ? (
          <details className="mt-5 text-xs text-slate-500 dark:text-slate-400">
            <summary className="cursor-pointer font-medium">{t('common.diagnostic_code', {}, 'Diagnostic code')}</summary>
            <code className="mt-2 inline-block rounded-lg bg-white/80 px-2 py-1 dark:bg-slate-900/70">
              {diagnosticCode}
            </code>
          </details>
        ) : null}
      </div>
    </div>
  );
}

export function PortalSiteSwitchingNotice({ message }: { message: string }) {
  return (
    <div className="rounded-[1.1rem] border border-blue-200 bg-blue-50/80 px-4 py-3 text-sm font-medium text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200">
      {message}
    </div>
  );
}
