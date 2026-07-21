'use client';

import React from 'react';
import {
  autoUpdate,
  flip,
  FloatingPortal,
  offset,
  shift,
  useDismiss,
  useFloating,
  useFocus,
  useHover,
  useInteractions,
  useRole,
} from '@floating-ui/react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

type BackofficeFrameProps = React.HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'portal';
};

type BackofficeHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  descriptionDisplay?: 'visible' | 'hint';
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
  detailDisplay?: 'visible' | 'hint';
  toneClassName?: string;
  size?: 'default' | 'compact';
};

type BackofficeMetricStripProps = {
  items: BackofficeMetricItem[];
  columnsClassName?: string;
  variant?: 'default' | 'portal';
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

type BackofficeDiagnosticNoticeProps = {
  message: string;
  staleDescription?: string;
  retryLabel?: string;
  onRetry?: () => void;
  className?: string;
};

type BackofficeDisclosureProps = {
  summary: string;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
};

export function BackofficePageStack({ children, className, ...props }: BackofficeFrameProps) {
  return (
    <div className={cn('space-y-6', className)} {...props}>
      {children}
    </div>
  );
}

type BackofficeInfoHintProps = {
  detail?: string;
  label?: string;
  className?: string;
};

export function BackofficeInfoHint({ detail, label, className }: BackofficeInfoHintProps) {
  const { t } = useLocale();
  const [open, setOpen] = React.useState(false);
  const tooltipId = React.useId();
  const {
    refs: { setReference, setFloating },
    floatingStyles,
    context,
  } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'bottom',
    strategy: 'fixed',
    whileElementsMounted: autoUpdate,
    middleware: [offset(8), flip({ padding: 12 }), shift({ padding: 12 })],
  });
  const hover = useHover(context, { move: false, restMs: 80 });
  const focus = useFocus(context);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'tooltip' });
  const { getReferenceProps, getFloatingProps } = useInteractions([hover, focus, dismiss, role]);

  if (!detail) {
    return null;
  }

  return (
    <>
      <span
        ref={setReference}
        tabIndex={0}
        aria-describedby={open ? tooltipId : undefined}
        aria-label={`${label || t('common.more_info', {}, 'More info')}: ${detail}`}
        className={cn(
          'backoffice-info-hint inline-flex h-5 w-5 shrink-0 cursor-help items-center justify-center rounded-full border border-slate-300 bg-white/80 text-[0.68rem] font-bold normal-case leading-none tracking-normal text-slate-500 transition hover:border-blue-300 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/30 dark:border-slate-700 dark:bg-slate-950/70 dark:text-slate-300 dark:hover:border-blue-500 dark:hover:text-blue-300',
          className
        )}
        {...getReferenceProps()}
      >
        i
      </span>
      {open ? (
        <FloatingPortal>
          <div
            ref={setFloating}
            id={tooltipId}
            className="backoffice-info-tooltip"
            style={floatingStyles}
            {...getFloatingProps()}
          >
            {detail}
          </div>
        </FloatingPortal>
      ) : null}
    </>
  );
}

export function BackofficePrimaryPanel({
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
            <div className="flex max-w-3xl items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-gray-950 dark:text-white md:text-[2rem]">
                {title}
              </h1>
              {descriptionDisplay === 'hint' ? <BackofficeInfoHint detail={description} /> : null}
            </div>
            {description && descriptionDisplay !== 'hint' ? (
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
  descriptionDisplay = 'visible',
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
          <div className="mt-2 flex items-center gap-2">
            <h2 className="text-2xl font-semibold text-gray-950 dark:text-white">
              {title}
            </h2>
            {descriptionDisplay === 'hint' ? <BackofficeInfoHint detail={description} /> : null}
          </div>
          {description && descriptionDisplay !== 'hint' ? (
            <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p>
          ) : null}
        </div>
        {aside || actions ? <div className="flex flex-wrap items-center gap-3">{aside}{actions}</div> : null}
      </div>
    </section>
  );
}

export function BackofficeSectionPanel({ children, className, variant = 'default', ...rest }: BackofficeFrameProps) {
  return (
    <div
      className={cn(
        variant === 'portal'
          ? 'rounded-[18px] border border-slate-200/80 bg-white p-4 shadow-none dark:border-slate-800 dark:bg-slate-950 md:p-5'
          : 'surface-panel rounded-[1.35rem] p-5 md:p-6',
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function BackofficeMetricStrip({ items, columnsClassName, variant = 'default' }: BackofficeMetricStripProps) {
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
            className={cn(
              variant === 'portal'
                ? 'rounded-xl border border-slate-200/75 bg-white px-4 py-3 shadow-none dark:border-slate-800 dark:bg-slate-950'
                : 'rounded-[1.1rem] border border-slate-200/80 bg-white/80 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-950/45'
            )}
          >
            <p
              className={cn(
                'flex items-center gap-1.5 text-gray-500 dark:text-gray-400',
                variant === 'portal'
                  ? 'text-xs font-medium'
                  : 'text-[0.68rem] font-semibold uppercase tracking-[0.18em]'
              )}
            >
              <span>{item.label}</span>
              {item.detail && item.detailDisplay === 'hint' ? (
                <BackofficeInfoHint detail={item.detail} className="h-4 w-4 text-[0.6rem]" />
              ) : null}
            </p>
            <p className={cn(
              'mt-2 font-semibold text-gray-950 dark:text-white',
              shouldCompact ? 'text-base leading-6' : 'text-[1.45rem] leading-8',
              item.toneClassName
            )}>
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

export function BackofficeDiagnosticNotice({
  message,
  staleDescription,
  retryLabel,
  onRetry,
  className,
}: BackofficeDiagnosticNoticeProps) {
  return (
    <div
      role="alert"
      className={cn(
        'rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200',
        className
      )}
    >
      <div className="font-semibold">{message}</div>
      {staleDescription ? <div className="mt-1 text-xs">{staleDescription}</div> : null}
      {!staleDescription && onRetry ? (
        <button type="button" className="btn btn-secondary btn-sm mt-3" onClick={onRetry}>
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

export function BackofficeDisclosure({
  summary,
  children,
  className,
  contentClassName,
}: BackofficeDisclosureProps) {
  return (
    <details className={cn('rounded-[1.35rem] border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950', className)}>
      <summary className="cursor-pointer select-none px-5 py-4 text-sm font-semibold text-slate-900 dark:text-white md:px-6">
        {summary}
      </summary>
      <div className={cn('border-t border-slate-200 p-5 dark:border-slate-800 md:p-6', contentClassName)}>
        {children}
      </div>
    </details>
  );
}

export function BackofficeStackCard({
  children,
  className,
  variant = 'default',
  ...rest
}: BackofficeFrameProps) {
  return (
    <div
      className={cn(
        variant === 'portal'
          ? 'rounded-xl border border-slate-200/75 bg-white px-4 py-3.5 shadow-none dark:border-slate-800 dark:bg-slate-950'
          : 'rounded-[1.1rem] border border-slate-200/80 bg-slate-50/75 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-950/45',
        className
      )}
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
