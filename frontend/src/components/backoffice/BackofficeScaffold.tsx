'use client';

import React from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

type BackofficeFrameProps = React.HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode;
  className?: string;
};

type BackofficeHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  aside?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
};

type BackofficePrimaryPanelProps = BackofficeHeaderProps & {
  children?: React.ReactNode;
  summary?: React.ReactNode;
  contentClassName?: string;
  summaryClassName?: string;
};

type BackofficeMetricItem = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  toneClassName?: string;
  size?: 'default' | 'compact';
};

type BackofficeMetricStripProps = {
  items: BackofficeMetricItem[];
  columnsClassName?: string;
};

type BackofficeSummaryStripProps = {
  items: BackofficeMetricItem[];
  className?: string;
};

type BackofficeEmptyStateProps = {
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  diagnosticCode?: string;
};

export function BackofficePageStack({ children, className }: BackofficeFrameProps) {
  return <div className={cn('space-y-6', className)}>{children}</div>;
}

export function BackofficePrimaryPanel({
  eyebrow,
  title,
  description,
  aside,
  actions,
  className,
  children,
  summary,
  contentClassName,
  summaryClassName,
}: BackofficePrimaryPanelProps) {
  return (
    <section className={cn('glass-panel overflow-hidden rounded-[1.6rem] p-0', className)}>
      <div className={cn('px-5 py-6 md:px-7 md:py-7', contentClassName)}>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            {eyebrow ? (
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-700 dark:text-blue-300">
                {eyebrow}
              </p>
            ) : null}
            <h1 className="max-w-3xl text-2xl font-semibold tracking-tight text-gray-950 dark:text-white md:text-[2rem]">
              {title}
            </h1>
            {description ? (
              <p className="max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p>
            ) : null}
          </div>
          {aside ? <div className="shrink-0">{aside}</div> : null}
        </div>
        {actions ? <div className="mt-6 flex flex-wrap gap-3">{actions}</div> : null}
        {children ? <div className="mt-5 space-y-4">{children}</div> : null}
      </div>
      {summary ? (
        <div
          className={cn(
            'border-t border-slate-200/80 bg-slate-50/70 px-5 py-5 dark:border-slate-800 dark:bg-slate-950/35 md:px-7 md:py-6',
            summaryClassName
          )}
        >
          {summary}
        </div>
      ) : null}
    </section>
  );
}

export function BackofficeLayer({
  eyebrow,
  title,
  description,
  aside,
  actions,
  className,
}: BackofficeHeaderProps) {
  return (
    <section className={cn('space-y-4', className)}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          {eyebrow ? (
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {eyebrow}
            </p>
          ) : null}
          <h2 className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">{title}</h2>
          {description ? (
            <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p>
          ) : null}
        </div>
        {aside || actions ? <div className="flex flex-wrap items-center gap-3">{aside}{actions}</div> : null}
      </div>
    </section>
  );
}

export function BackofficeSectionPanel({ children, className }: BackofficeFrameProps) {
  return <div className={cn('surface-panel rounded-[1.35rem] p-5 md:p-6', className)}>{children}</div>;
}

export function BackofficeMetricStrip({ items, columnsClassName }: BackofficeMetricStripProps) {
  return (
    <div className={cn('grid gap-3 md:grid-cols-2 xl:grid-cols-4', columnsClassName)}>
      {items.map((item) => {
        const primitiveValue = typeof item.value === 'string' || typeof item.value === 'number'
          ? String(item.value)
          : '';
        const shouldCompact =
          item.size === 'compact' ||
          Boolean(primitiveValue && (primitiveValue.length > 10 || /[-/：:]/.test(primitiveValue)));

        return (
          <div
            key={item.label}
            className="rounded-[1.1rem] border border-slate-200/80 bg-white/80 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-950/45"
          >
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {item.label}
            </p>
            <p className={cn(
              'mt-2 font-semibold text-gray-950 dark:text-white',
              shouldCompact ? 'text-base leading-6' : 'text-[1.45rem] leading-8',
              item.toneClassName
            )}>
              {item.value}
            </p>
            {item.detail ? (
              <p className="mt-2 text-xs leading-5 text-gray-500 dark:text-gray-400">{item.detail}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function BackofficeSummaryStrip({ items, className }: BackofficeSummaryStripProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2 text-sm', className)}>
      {items.map((item) => (
        <div
          key={item.label}
          className="inline-flex min-h-9 items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-300"
          title={item.detail || undefined}
        >
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</span>
          <span className={cn('font-semibold text-slate-950 dark:text-white', item.toneClassName)}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function BackofficeStackCard({
  children,
  className,
  ...rest
}: BackofficeFrameProps) {
  return (
    <div
      className={cn('rounded-[1.1rem] border border-slate-200/80 bg-slate-50/75 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-950/45', className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function BackofficeEmptyState({
  title,
  description,
  action,
  className,
  diagnosticCode,
}: BackofficeEmptyStateProps) {
  const { t } = useLocale();
  return (
    <BackofficeStackCard className={cn('py-8 text-center', className)}>
      <div className="mx-auto max-w-xl">
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p>
        {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
        {diagnosticCode ? (
          <details className="mt-5 text-xs text-slate-500 dark:text-slate-400">
            <summary className="cursor-pointer font-medium">{t('common.diagnostic_code', {}, 'Diagnostic code')}</summary>
            <code className="mt-2 inline-block rounded-lg bg-white/80 px-2 py-1 dark:bg-slate-900/70">
              {diagnosticCode}
            </code>
          </details>
        ) : null}
      </div>
    </BackofficeStackCard>
  );
}
