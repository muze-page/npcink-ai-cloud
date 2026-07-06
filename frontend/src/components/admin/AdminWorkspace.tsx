'use client';

import React from 'react';
import { cn } from '@/lib/utils';

type AdminWorkspaceFrameProps = React.HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode;
  className?: string;
};

type AdminWorkspaceSplitProps = {
  primary: React.ReactNode;
  inspector: React.ReactNode;
  className?: string;
  primaryClassName?: string;
  inspectorClassName?: string;
};

type AdminMetricPanelItem = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  toneClassName?: string;
};

type AdminMetricPanelProps = {
  items: AdminMetricPanelItem[];
  className?: string;
};

type AdminInspectorPaneProps = {
  title: string;
  description?: string;
  status?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

type AdminTableShellProps = {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

export function AdminWorkspacePage({ children, className, ...rest }: AdminWorkspaceFrameProps) {
  return (
    <div data-ui="admin-workspace-page" className={cn('space-y-5', className)} {...rest}>
      {children}
    </div>
  );
}

export function AdminWorkspaceSplit({
  primary,
  inspector,
  className,
  primaryClassName,
  inspectorClassName,
}: AdminWorkspaceSplitProps) {
  return (
    <section
      data-ui="admin-workspace-split"
      className={cn('surface-panel overflow-hidden rounded-[1.35rem] p-0', className)}
    >
      <div className="grid divide-y divide-slate-200/80 dark:divide-slate-800 xl:grid-cols-[1.15fr_0.85fr] xl:divide-x xl:divide-y-0">
        <div className={cn('p-5 md:p-6', primaryClassName)}>{primary}</div>
        <div className={cn('p-5 md:p-6', inspectorClassName)}>{inspector}</div>
      </div>
    </section>
  );
}

export function AdminMetricPanel({ items, className }: AdminMetricPanelProps) {
  return (
    <div data-ui="admin-metric-panel" className={cn('grid gap-3 md:grid-cols-2 xl:grid-cols-4', className)}>
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-xl border border-slate-200/80 bg-white/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-950/45"
        >
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {item.label}
          </p>
          <p className={cn('mt-2 text-lg font-semibold text-slate-950 dark:text-white', item.toneClassName)}>
            {item.value}
          </p>
          {item.detail ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.detail}</p> : null}
        </div>
      ))}
    </div>
  );
}

export function AdminInspectorPane({
  title,
  description,
  status,
  children,
  className,
}: AdminInspectorPaneProps) {
  return (
    <aside data-ui="admin-inspector-pane" className={cn('space-y-4', className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
          {description ? <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p> : null}
        </div>
        {status ? <div className="shrink-0">{status}</div> : null}
      </div>
      {children}
    </aside>
  );
}

export function AdminTableShell({
  title,
  description,
  actions,
  children,
  className,
}: AdminTableShellProps) {
  return (
    <section
      data-ui="admin-table-shell"
      className={cn('surface-panel overflow-hidden rounded-[1.25rem] p-0', className)}
    >
      <div className="flex flex-col gap-3 border-b border-slate-200/80 px-4 py-3 dark:border-slate-800 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-950 dark:text-white">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}
