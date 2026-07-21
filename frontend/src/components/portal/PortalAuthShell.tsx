import type { ReactNode } from 'react';
import { PortalPageStack, PortalSection } from '@/components/portal/PortalScaffold';

interface PortalAuthShellProps {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  aside: ReactNode;
}

export function PortalAuthShell({
  eyebrow,
  title,
  description,
  children,
  aside,
}: PortalAuthShellProps) {
  return (
    <main className="mx-auto flex min-h-[72vh] w-full max-w-5xl items-center px-4 py-10" data-portal-auth="shell">
      <PortalPageStack>
        <PortalSection className="w-full overflow-hidden p-0">
          <div className="grid gap-0 lg:grid-cols-[minmax(0,1.05fr)_minmax(18rem,0.75fr)]">
            <div className="space-y-6 p-5 md:p-7">
              <header>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-700 dark:text-blue-300">
                  {eyebrow}
                </p>
                <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-950 dark:text-white md:text-[2rem]">
                  {title}
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-gray-600 dark:text-gray-300">
                  {description}
                </p>
              </header>
              {children}
            </div>
            <aside className="border-t border-slate-200/80 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-950/35 md:p-7 lg:border-l lg:border-t-0">
              {aside}
            </aside>
          </div>
        </PortalSection>
      </PortalPageStack>
    </main>
  );
}
