import { Skeleton } from '@/components/ui/Skeleton';

function MetricSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white/80 px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/55">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="mt-4 h-8 w-20" />
      <Skeleton className="mt-3 h-3 w-full max-w-44" />
    </div>
  );
}

function RowSkeleton() {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-200/70 px-4 py-3 last:border-b-0 dark:border-slate-800">
      <div className="min-w-0 flex-1">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="mt-2 h-3 w-full max-w-md" />
      </div>
      <Skeleton className="h-8 w-24 rounded-xl" />
    </div>
  );
}

export function AdminRouteSkeleton() {
  return (
    <div className="admin-route-skeleton space-y-5" aria-busy="true" aria-label="Loading admin page">
      <div className="h-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800">
        <div className="admin-route-progress h-full w-1/3 rounded-full bg-blue-600 dark:bg-blue-400" />
      </div>

      <section className="rounded-[1.35rem] border border-slate-200/80 bg-white/84 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950/55">
        <div className="grid gap-5 xl:grid-cols-[1fr_34rem] xl:items-start">
          <div className="space-y-4">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-9 w-full max-w-sm" />
            <Skeleton className="h-4 w-full max-w-2xl" />
            <Skeleton className="h-4 w-full max-w-xl" />
            <div className="flex flex-wrap gap-2 pt-2">
              <Skeleton className="h-10 w-28 rounded-xl" />
              <Skeleton className="h-10 w-32 rounded-xl" />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="rounded-[1.35rem] border border-slate-200/80 bg-white/80 shadow-sm dark:border-slate-800 dark:bg-slate-950/50">
          <div className="border-b border-slate-200/70 px-4 py-4 dark:border-slate-800">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-7 w-56" />
          </div>
          <RowSkeleton />
          <RowSkeleton />
          <RowSkeleton />
          <RowSkeleton />
        </div>

        <aside className="rounded-[1.35rem] border border-slate-200/80 bg-white/78 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/50">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="mt-3 h-6 w-40" />
          <div className="mt-5 space-y-3">
            <Skeleton className="h-20 w-full rounded-2xl" />
            <Skeleton className="h-20 w-full rounded-2xl" />
            <Skeleton className="h-20 w-full rounded-2xl" />
          </div>
        </aside>
      </section>
    </div>
  );
}
