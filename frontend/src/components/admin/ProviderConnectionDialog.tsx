'use client';

import type { FormEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';

type ProviderConnectionDialogProps = {
  open: boolean;
  title: string;
  titleId: string;
  headerAccessory?: ReactNode;
  message?: string;
  error?: string;
  saving: boolean;
  closeLabel: string;
  cancelLabel: string;
  saveLabel: string;
  savingLabel: string;
  footerNotice: string;
  onClose: () => void;
  onSubmit: () => void;
  children: ReactNode;
};

export function ProviderConnectionDialog({
  open,
  title,
  titleId,
  headerAccessory,
  message,
  error,
  saving,
  closeLabel,
  cancelLabel,
  saveLabel,
  savingLabel,
  footerNotice,
  onClose,
  onSubmit,
  children,
}: ProviderConnectionDialogProps) {
  if (!open) return null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/45 px-4 py-6 backdrop-blur-sm sm:py-10"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div className="flex max-h-[calc(100vh-3rem)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3 dark:border-slate-800">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 id={titleId} className="text-base font-semibold text-slate-950 dark:text-white">
              {title}
            </h3>
            {headerAccessory}
          </div>
          <button
            type="button"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-sm font-semibold text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:text-white"
            disabled={saving}
            onClick={onClose}
            aria-label={closeLabel}
          >
            <span aria-hidden="true">X</span>
          </button>
        </div>

        {message || error ? (
          <div className="grid gap-2 border-b border-slate-200 px-5 py-3 dark:border-slate-800">
            {message ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
                {message}
              </div>
            ) : null}
            {error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
                {error}
              </div>
            ) : null}
          </div>
        ) : null}

        <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit}>
          <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto px-5 py-4">
            {children}
          </div>
          <div className="flex flex-col gap-3 border-t border-slate-200 bg-white px-5 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
            <span>{footerNotice}</span>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={onClose}>
                {cancelLabel}
              </button>
              <button
                type="submit"
                disabled={saving}
                className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? savingLabel : saveLabel}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
