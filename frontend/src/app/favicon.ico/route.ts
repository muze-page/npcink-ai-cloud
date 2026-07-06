const faviconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0f172a"/>
  <path d="M8 21.5V10.5h4.2l3.8 6.1 3.8-6.1H24v11h-3.4v-6.2l-3.5 5.4h-2.2l-3.5-5.4v6.2H8z" fill="#f8fafc"/>
</svg>`;

export function GET() {
  return new Response(faviconSvg, {
    headers: {
      'Cache-Control': 'public, max-age=86400',
      'Content-Type': 'image/svg+xml',
    },
  });
}
