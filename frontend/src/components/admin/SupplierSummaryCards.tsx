type SupplierSummaryCardsProps = {
  readyModelSupplierCount: number;
  modelSupplierCount: number;
  attentionSupplierCount: number;
  translate: (key: string, fallback: string) => string;
};

export function SupplierSummaryCards({
  readyModelSupplierCount,
  modelSupplierCount,
  attentionSupplierCount,
  translate,
}: SupplierSummaryCardsProps) {
  return (
    <dl
      data-ui="supplier-summary-strip"
      className="grid grid-cols-2 divide-x divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white/70 dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-950/35"
    >
      <div className="min-w-0 px-3 py-3 sm:px-4">
        <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {translate('overview_model_suppliers', 'Model suppliers')}
        </dt>
        <dd className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
          {readyModelSupplierCount}/{modelSupplierCount}
        </dd>
        <p className="mt-0.5 hidden text-xs text-slate-500 dark:text-slate-400 sm:block">
          {translate('overview_ready_ratio_detail', 'ready / total')}
        </p>
      </div>
      <div className="min-w-0 px-3 py-3 sm:px-4">
        <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {translate('overview_attention_suppliers', 'Needs attention')}
        </dt>
        <dd className={`mt-1 text-lg font-semibold ${
          attentionSupplierCount > 0
            ? 'text-amber-600 dark:text-amber-400'
            : 'text-emerald-600 dark:text-emerald-400'
        }`}>
          {attentionSupplierCount}
        </dd>
        <p className="mt-0.5 hidden text-xs text-slate-500 dark:text-slate-400 sm:block">
          {translate('overview_attention_detail', 'Disabled, missing, or unhealthy supplier channels')}
        </p>
      </div>
    </dl>
  );
}
