import { Suspense } from 'react';
import { PortalNavbar } from '@/components/portal/PortalNavbar';
import { PortalSessionBoundary } from '@/components/portal/PortalSessionBoundary';
import { PortalSessionProvider } from '@/hooks/useSession';

export default function PortalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <PortalSessionProvider>
      <PortalSessionBoundary>
        <div className="portal-shell flex min-h-[100dvh] flex-col">
          <Suspense fallback={null}>
            <PortalNavbar />
          </Suspense>
          <main className="flex-1 bg-[#f5f5f7] dark:bg-slate-950">
            <div className="container mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-8">
              {children}
            </div>
          </main>
        </div>
      </PortalSessionBoundary>
    </PortalSessionProvider>
  );
}
