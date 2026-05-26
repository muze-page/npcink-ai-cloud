'use client';

import dynamic from 'next/dynamic';
import { LoadingFallback } from '@/components/ui/LoadingFallback';

const PortalAuditClient = dynamic(
  () => import('./PortalAuditClient').then((module) => module.PortalAuditClient),
  {
    ssr: false,
    loading: () => <LoadingFallback />,
  }
);

export default function PortalAuditPage() {
  return <PortalAuditClient />;
}
