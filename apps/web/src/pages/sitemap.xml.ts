import type { APIRoute } from 'astro';
import { plannedTools, toolPath } from '../components/toolCatalog';

/** Only hand-reviewed indexable public routes belong in the sitemap. */
const publicPages = [
  '/',
  '/tools/',
  '/audit/',
  '/guides/',
  '/guides/robots-txt-basics/',
  '/guides/title-tags/',
  '/docs/',
  '/open-source/',
  '/open-source/benchmarks/',
  '/about/',
  '/contact/',
  '/privacy/',
  '/terms/',
];
const entries = [
  ...publicPages,
  ...plannedTools.filter((tool) => tool.status === 'available').map(toolPath),
];
const escapeXml = (value: string) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');

export const GET: APIRoute = ({ site }) => {
  const origin = site ?? new URL('https://aiseoonline.com');
  const urls = [...new Set(entries)].map((path) => {
    const loc = escapeXml(new URL(path, origin).toString());
    return `  <url><loc>${loc}</loc></url>`;
  });
  const content = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`;
  return new Response(content, {
    headers: {
      'Content-Type': 'application/xml; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
};
