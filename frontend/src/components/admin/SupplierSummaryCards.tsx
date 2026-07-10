type SupplierSummaryCardsProps = {
  readyModelSupplierCount: number;
  modelSupplierCount: number;
  readyCapabilitySupplierCount: number;
  capabilitySupplierCount: number;
  attentionSupplierCount: number;
  translate: (key: string, fallback: string) => string;
};

export function SupplierSummaryCards({
  readyModelSupplierCount,
  modelSupplierCount,
  readyCapabilitySupplierCount,
  capabilitySupplierCount,
  attentionSupplierCount,
  translate,
}: SupplierSummaryCardsProps) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {translate('overview_model_suppliers', 'Model suppliers')}
        </p>
        <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
          {readyModelSupplierCount}/{modelSupplierCount}
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {translate('overview_ready_ratio_detail', 'ready / total')}
        </p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {translate('overview_capability_suppliers', 'Capability suppliers')}
        </p>
        <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
          {readyCapabilitySupplierCount}/{capabilitySupplierCount}
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {translate('overview_ready_ratio_detail', 'ready / total')}
        </p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {translate('overview_attention_suppliers', 'Needs attention')}
        </p>
        <p className={`mt-2 text-lg font-semibold ${
          attentionSupplierCount > 0
            ? 'text-amber-600 dark:text-amber-400'
            : 'text-emerald-600 dark:text-emerald-400'
        }`}>
          {attentionSupplierCount}
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {translate('overview_attention_detail', 'Disabled, missing, or unhealthy supplier channels')}
        </p>
      </div>
    </div>
  );
}
