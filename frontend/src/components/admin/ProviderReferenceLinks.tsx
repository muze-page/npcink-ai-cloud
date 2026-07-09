type ProviderReferenceLinkItem = {
  key: string;
  labelKey: string;
  fallback: string;
  href: string;
};

type ProviderReferenceLinksProps = {
  items: ProviderReferenceLinkItem[];
  label: string;
  translate: (key: string, fallback: string) => string;
  variant?: 'pills' | 'inline';
};

export function ProviderReferenceLinks({
  items,
  label,
  translate,
  variant = 'pills',
}: ProviderReferenceLinksProps) {
  if (!items.length) {
    return null;
  }

  if (variant === 'inline') {
    return (
      <div className="mt-2 flex flex-wrap gap-2 text-xs" aria-label={label}>
        {items.map((item) => (
          <a
            key={item.key}
            className="font-semibold text-slate-600 underline decoration-slate-300 underline-offset-4 transition hover:text-slate-950 dark:text-slate-300 dark:decoration-slate-700 dark:hover:text-white"
            href={item.href}
            target="_blank"
            rel="noreferrer"
          >
            {translate(item.labelKey, item.fallback)}
          </a>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {items.map((item) => (
          <a
            key={item.key}
            className="rounded-full border border-slate-200 px-3 py-1 font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-900"
            href={item.href}
            target="_blank"
            rel="noreferrer"
          >
            {translate(item.labelKey, item.fallback)}
          </a>
        ))}
      </div>
    </div>
  );
}
