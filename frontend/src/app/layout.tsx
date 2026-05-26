import type { Metadata } from 'next';
import { MiniDevDock } from '@/components/dev/MiniDevDock';
import { ToastProvider } from '@/components/ui/Toast';
import { LocaleProvider } from '@/contexts/LocaleContext';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { DEFAULT_LOCALE } from '@/lib/i18n';
import './globals.css';

export const metadata: Metadata = {
  title: 'Magick AI Cloud',
  description: 'Hosted AI runtime and service platform',
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
              <MiniDevDock />
            </ToastProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
