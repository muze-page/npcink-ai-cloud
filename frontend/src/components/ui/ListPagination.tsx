'use client';

import { useLocale } from '@/contexts/LocaleContext';

type ListPaginationProps = {
  offset: number;
  limit: number;
  total: number;
  isLoading?: boolean;
  onOffsetChange: (offset: number) => void;
  className?: string;
};

export function ListPagination({
  offset,
  limit,
  total,
  isLoading = false,
  onOffsetChange,
  className = '',
}: ListPaginationProps) {
  const { t } = useLocale();
  const safeTotal = Math.max(0, total);
  const safeOffset = Math.max(0, offset);
  const start = safeTotal > 0 ? safeOffset + 1 : 0;
  const end = Math.min(safeOffset + limit, safeTotal);
  const hasPrevious = safeOffset > 0;
  const hasNext = safeOffset + limit < safeTotal;

  if (safeTotal <= limit && safeOffset === 0) {
    return null;
  }

  return (
    <nav
      className={`flex flex-col gap-3 border-t border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 ${className}`}
      aria-label={t('common.pagination', {}, 'Pagination')}
    >
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {t(
          'common.pagination_summary',
          { start: String(start), end: String(end), total: String(safeTotal) },
          `${start}-${end} of ${safeTotal}`
        )}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={!hasPrevious || isLoading}
          onClick={() => onOffsetChange(Math.max(0, safeOffset - limit))}
        >
          {t('common.previous', {}, 'Previous')}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={!hasNext || isLoading}
          onClick={() => onOffsetChange(safeOffset + limit)}
        >
          {t('common.next_page', {}, 'Next page')}
        </button>
      </div>
    </nav>
  );
}
