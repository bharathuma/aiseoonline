import type { APIRoute } from 'astro';

export const GET: APIRoute = ({ site }) => {
  const base = site ?? new URL('https://aiseoonline.com');
  const text = [
    'User-agent: *',
    'Allow: /',
    'Disallow: /internal/',
    'Disallow: /api/',
    '',
    'Sitemap: ' + new URL('/sitemap.xml', base).toString(),
    '',
  ].join('\n');
  return new Response(text, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
};
