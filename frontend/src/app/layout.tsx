import type { Metadata } from 'next';
import { ToastProvider } from '@/components/ui/Toast';
import { LocaleProvider } from '@/contexts/LocaleContext';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { DEFAULT_LOCALE } from '@/lib/i18n';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'Npcink AI Cloud',
    template: '%s · Npcink AI Cloud',
  },
  description: '面向 WordPress 的托管 AI 运行、用量记录与服务诊断。',
  metadataBase: new URL(process.env.CLOUD_PUBLIC_BASE_URL || 'https://cloud.npc.ink'),
  openGraph: {
    type: 'website',
    title: 'Npcink AI Cloud',
    description: '面向 WordPress 的托管 AI 运行、用量记录与服务诊断。',
    siteName: 'Npcink AI Cloud',
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang={DEFAULT_LOCALE} suppressHydrationWarning data-scroll-behavior="smooth">
      <body className="min-h-screen bg-background text-foreground antialiased">
        <ThemeProvider>
          <LocaleProvider>
            <ToastProvider>
              {children}
            </ToastProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
