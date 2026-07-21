type SupplierToolbarProps = {
  connectionSearch: string;
  onConnectionSearchChange: (value: string) => void;
  hasLatestOperation: boolean;
  onOpenLatestOperation: () => void;
  onAddModelSupplier: () => void;
  translate: (key: string, fallback: string) => string;
};

export function SupplierToolbar({
  connectionSearch,
  onConnectionSearchChange,
  hasLatestOperation,
  onOpenLatestOperation,
  onAddModelSupplier,
  translate,
}: SupplierToolbarProps) {
  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-end">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center xl:justify-end">
        <label className="grid w-full gap-1 sm:w-[22rem]">
          <span className="sr-only">{translate('field_search_connections', 'Search suppliers')}</span>
          <input
            className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            value={connectionSearch}
            onChange={(event) => onConnectionSearchChange(event.target.value)}
            placeholder={translate('placeholder_search_connections', 'Name, provider, model, capability')}
          />
        </label>
        {hasLatestOperation ? (
          <button type="button" className="btn btn-secondary justify-center" onClick={onOpenLatestOperation}>
            {translate('action_latest_operation', 'Latest operation')}
          </button>
        ) : null}
        <button type="button" className="btn btn-primary justify-center" onClick={onAddModelSupplier}>
          {translate('action_add_model_supplier', 'Add model supplier')}
        </button>
      </div>
    </div>
  );
}
