import Link from 'next/link';

export default function ServiceStatusPage() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950 dark:bg-slate-950 dark:text-slate-50">
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
        <div className="space-y-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
              Npcink AI Cloud
            </p>
            <h1 className="mt-3 text-3xl font-semibold tracking-normal">
              Hosted runtime service
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              This Cloud deployment exposes runtime, catalog, usage, billing detail,
              minimal portal, and internal operator diagnostics.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link className="btn btn-primary" href="/portal/login">
              Portal login
            </Link>
            <Link className="btn btn-secondary" href="/admin/login">
              Admin login
            </Link>
            <Link className="btn btn-outline" href="/api/health">
              Health
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
