import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: ['/', '/status', '/help', '/privacy', '/terms', '/portal/login', '/portal/register'],
        disallow: ['/admin/', '/portal/'],
      },
    ],
    sitemap: 'https://cloud.npc.ink/sitemap.xml',
  };
}
