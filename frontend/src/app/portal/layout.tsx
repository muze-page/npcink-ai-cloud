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
        <div className="flex min-h-screen flex-col">
          <Suspense fallback={null}>
            <PortalNavbar />
          </Suspense>
          <main className="flex-1 bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.08),transparent_22rem),linear-gradient(180deg,#f8fbff_0%,#f7f8fc_54%,#eef3fb_100%)] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.08),transparent_20rem),linear-gradient(180deg,#07111f_0%,#08101d_54%,#030712_100%)]">
            <div className="container mx-auto px-4 py-8">
              {children}
            </div>
          </main>
        </div>
      </PortalSessionBoundary>
    </PortalSessionProvider>
  );
}
