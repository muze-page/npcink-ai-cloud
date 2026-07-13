'use client';

import React from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

type PortalFrameProps = React.HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode;
  variant?: 'default' | 'portal';
};

type PortalMetricItem = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  detailDisplay?: 'visible' | 'hint';
  toneClassName?: string;
  size?: 'default' | 'compact';
};

type PortalMetricStripProps = {
  items: PortalMetricItem[];
  columnsClassName?: string;
  variant?: 'default' | 'portal';
};

type PortalPrimaryPanelProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  descriptionDisplay?: 'visible' | 'hint';
  aside?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
  summary?: React.ReactNode;
  contentClassName?: string;
  summaryClassName?: string;
};

type PortalEmptyStateProps = {
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  diagnosticCode?: string;
};

export function PortalPageStack({ children, className, variant: _variant, ...props }: PortalFrameProps) {
  return <div className={cn('space-y-6', className)} {...props}>{children}</div>;
}

export function PortalSection({ children, className, variant: _variant, ...props }: PortalFrameProps) {
  return (
    <div
      className={cn('rounded-[18px] border border-slate-200/80 bg-white p-4 shadow-none dark:border-slate-800 dark:bg-slate-950 md:p-5', className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function PortalCard({ children, className, variant: _variant, ...props }: PortalFrameProps) {
  return (
    <div
      className={cn('rounded-xl border border-slate-200/75 bg-white px-4 py-3.5 shadow-none dark:border-slate-800 dark:bg-slate-950', className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function PortalMetricStrip({ items, columnsClassName }: PortalMetricStripProps) {
  return (
    <div className={cn('grid gap-3 md:grid-cols-2 xl:grid-cols-4', columnsClassName)}>
      {items.map((item) => {
        const primitiveValue = typeof item.value === 'string' || typeof item.value === 'number'
          ? String(item.value)
          : '';
        const compact = item.size === 'compact'
          || Boolean(primitiveValue && (primitiveValue.length > 10 || /[-/：:]/.test(primitiveValue)));
        return (
          <div key={item.label} className="rounded-xl border border-slate-200/75 bg-white px-4 py-3 shadow-none dark:border-slate-800 dark:bg-slate-950">
            <p className="flex items-center gap-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">
              <span>{item.label}</span>
              {item.detail && item.detailDisplay === 'hint' ? (
                <span className="cursor-help" title={item.detail} aria-label={`${item.label}: ${item.detail}`}>ⓘ</span>
              ) : null}
            </p>
            <p className={cn('mt-2 font-semibold text-gray-950 dark:text-white', compact ? 'text-base leading-6' : 'text-[1.45rem] leading-8', item.toneClassName)}>
              {item.value}
            </p>
            {item.detail && item.detailDisplay !== 'hint' ? (
              <p className="mt-2 text-xs leading-5 text-gray-500 dark:text-gray-400">{item.detail}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function PortalPrimaryPanel({
  eyebrow,
  title,
  description,
  descriptionDisplay = 'visible',
  aside,
  actions,
  className,
  children,
  summary,
  contentClassName,
  summaryClassName,
}: PortalPrimaryPanelProps) {
  return (
    <section className={cn('glass-panel overflow-hidden rounded-[1.6rem] p-0', className)}>
      <div className={cn('px-5 py-6 md:px-7 md:py-7', contentClassName)}>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-700 dark:text-blue-300">{eyebrow}</p> : null}
            <div className="flex max-w-3xl items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-gray-950 dark:text-white md:text-[2rem]">{title}</h1>
              {description && descriptionDisplay === 'hint' ? <span className="cursor-help" title={description}>ⓘ</span> : null}
            </div>
            {description && descriptionDisplay !== 'hint' ? <p className="max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p> : null}
          </div>
          {aside ? <div className="shrink-0">{aside}</div> : null}
        </div>
        {actions ? <div className="mt-6 flex flex-wrap gap-3">{actions}</div> : null}
        {children ? <div className="mt-5 space-y-4">{children}</div> : null}
      </div>
      {summary ? <div className={cn('border-t border-slate-200/80 bg-slate-50/70 px-5 py-5 dark:border-slate-800 dark:bg-slate-950/35 md:px-7 md:py-6', summaryClassName)}>{summary}</div> : null}
    </section>
  );
}

export function PortalScaffoldEmptyState({ title, description, action, className, diagnosticCode }: PortalEmptyStateProps) {
  const { t } = useLocale();
  return (
    <PortalCard className={cn('py-8 text-center', className)}>
      <div className="mx-auto max-w-xl">
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p>
        {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
        {diagnosticCode ? (
          <details className="mt-5 text-xs text-slate-500 dark:text-slate-400">
            <summary className="cursor-pointer font-medium">{t('common.diagnostic_code', {}, 'Diagnostic code')}</summary>
            <code className="mt-2 inline-block rounded-lg bg-slate-50 px-2 py-1 dark:bg-slate-900/70">{diagnosticCode}</code>
          </details>
        ) : null}
      </div>
    </PortalCard>
  );
}
