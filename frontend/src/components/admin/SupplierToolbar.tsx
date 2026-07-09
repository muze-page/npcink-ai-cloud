import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';

export type SupplierTypeFilter = 'model' | 'capability';

type SupplierToolbarProps = {
  supplierTypeFilter: SupplierTypeFilter;
  onSupplierTypeFilterChange: (value: SupplierTypeFilter) => void;
  connectionSearch: string;
  onConnectionSearchChange: (value: string) => void;
  onAddModelSupplier: () => void;
  onAddCapabilitySupplier: () => void;
  translate: (key: string, fallback: string) => string;
};

export function SupplierToolbar({
  supplierTypeFilter,
  onSupplierTypeFilterChange,
  connectionSearch,
  onConnectionSearchChange,
  onAddModelSupplier,
  onAddCapabilitySupplier,
  translate,
}: SupplierToolbarProps) {
  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div className="flex flex-col gap-2">
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
          {translate('field_supplier_type_filter', 'Supplier type')}
        </span>
        <div
          className="flex flex-wrap gap-2"
          role="tablist"
          aria-label={translate('supplier_type_tabs_label', 'Supplier type')}
        >
          {([
            ['model', translate('supplier_filter_model', 'Model suppliers')],
            ['capability', translate('supplier_filter_capability', 'Capability suppliers')],
          ] as Array<[SupplierTypeFilter, string]>).map(([value, label]) => (
            <BackofficeFilterPill
              key={value}
              role="tab"
              aria-selected={supplierTypeFilter === value}
              active={supplierTypeFilter === value}
              onClick={() => onSupplierTypeFilterChange(value)}
            >
              {label}
            </BackofficeFilterPill>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center xl:justify-end">
        <label className="grid min-w-[16rem] gap-1 sm:w-[22rem]">
          <span className="sr-only">{translate('field_search_connections', 'Search suppliers')}</span>
          <input
            className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            value={connectionSearch}
            onChange={(event) => onConnectionSearchChange(event.target.value)}
            placeholder={translate('placeholder_search_connections', 'Name, provider, model, capability')}
          />
        </label>
        <button type="button" className="btn btn-primary justify-center" onClick={onAddModelSupplier}>
          {translate('action_add_model_supplier', 'Add model supplier')}
        </button>
        <button type="button" className="btn btn-secondary justify-center" onClick={onAddCapabilitySupplier}>
          {translate('action_add_capability_supplier', 'Add capability supplier')}
        </button>
      </div>
    </div>
  );
}
