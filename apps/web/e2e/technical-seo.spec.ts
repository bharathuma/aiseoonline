import { expect, test } from '@playwright/test';

const tools = [
  'robots-txt-validator',
  'xml-sitemap-validator',
  'meta-tag-checker',
  'redirect-chain-checker',
  'canonical-url-checker',
  'structured-data-checker',
  'heading-structure-analyzer',
  'internal-link-checker',
  'social-metadata-checker',
  'ai-meta-suggestions',
] as const;

test('ten distinct indexable tools have useful editorial content, links and matching schema', async ({
  page,
}) => {
  const seenTitles = new Set<string>();
  const seenDescriptions = new Set<string>();
  for (const slug of tools) {
    await page.goto(`/tools/${slug}/`);
    const title = await page.title();
    const description = await page.locator('meta[name="description"]').getAttribute('content');
    expect(title.length).toBeGreaterThan(25);
    expect(description?.length).toBeGreaterThan(70);
    expect(seenTitles.has(title), `Duplicate title on ${slug}`).toBe(false);
    expect(seenDescriptions.has(description ?? ''), `Duplicate description on ${slug}`).toBe(false);
    seenTitles.add(title);
    seenDescriptions.add(description ?? '');

    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      'href',
      `https://aiseoonline.com/tools/${slug}/`,
    );
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    for (const heading of [
      'What this tool checks',
      'How to use the checker',
      'Troubleshooting',
      'Limits of this check',
      'Frequently asked questions',
      'Related checks',
    ]) {
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    }
    const structured = await page.locator('script[type="application/ld+json"]').allTextContents();
    expect(structured).toHaveLength(1);
    const objects = JSON.parse(structured[0]) as Array<Record<string, unknown>>;
    const breadcrumbs = objects.find((item) => item['@type'] === 'BreadcrumbList');
    expect(breadcrumbs).toBeDefined();
    const faq = objects.find((item) => item['@type'] === 'FAQPage');
    expect(faq).toBeDefined();
    const questions = faq?.mainEntity as Array<{ name: string; acceptedAnswer: { text: string } }>;
    expect(questions.length).toBeGreaterThanOrEqual(2);
    for (const question of questions) {
      await expect(page.getByRole('heading', { name: question.name })).toBeVisible();
      await expect(page.getByText(question.acceptedAnswer.text, { exact: true })).toBeVisible();
    }
    if (slug !== 'ai-meta-suggestions') {
      expect(objects.some((item) => item['@type'] === 'WebApplication')).toBe(true);
    }
    await expect(
      page.getByRole('navigation', { name: 'Related SEO tools' }).getByRole('link').first(),
    ).toBeVisible();
    await expect(page.locator('[data-ad-placeholder]')).toHaveCount(0);
  }
  expect(seenTitles.size).toBe(10);
});

test('sitemap and robots include public pages and exclude all internal pages', async ({
  request,
}) => {
  const sitemap = await request.get('/sitemap.xml');
  expect(sitemap.status()).toBe(200);
  const xmlType = (sitemap.headers()['content-type'] ?? '').split(';')[0];
  expect(['text/xml', 'application/xml']).toContain(xmlType);
  const xml = await sitemap.text();
  const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  expect(new Set(urls).size).toBe(urls.length);
  for (const slug of tools) expect(urls).toContain(`https://aiseoonline.com/tools/${slug}/`);
  for (const path of ['/about/', '/contact/', '/privacy/', '/terms/', '/guides/']) {
    expect(urls).toContain(`https://aiseoonline.com${path}`);
  }
  expect(xml).not.toContain('/internal/');
  expect(xml).not.toContain('/docs/components/');
  expect(xml).not.toContain('/api/v1/');
  const robots = await request.get('/robots.txt');
  expect(robots.status()).toBe(200);
  const rules = await robots.text();
  expect(rules).toContain('Sitemap: https://aiseoonline.com/sitemap.xml');
  expect(rules).toContain('Disallow: /internal/');
  expect(rules).toContain('Disallow: /api/');
});

test('internal pages remain noindex and public policy pages disclose limitations', async ({
  page,
}) => {
  for (const path of ['/internal/audit/', '/internal/rag-chat/', '/docs/components/']) {
    await page.goto(path);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
  }
  for (const path of ['/about/', '/contact/', '/privacy/', '/terms/']) {
    await page.goto(path);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      'href',
      `https://aiseoonline.com${path}`,
    );
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  }
  await page.goto('/privacy/');
  await expect(page.getByRole('heading', { name: 'Analytics is disabled' })).toBeVisible();
  await expect(page.getByText(/not send first-party analytics events/)).toBeVisible();
  await expect(page.locator('[data-analytics-choice]')).toHaveCount(0);
});

test('public pages trigger no ad network or analytics collection by default', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));
  await page.goto('/tools/meta-tag-checker/');
  await page.goto('/privacy/');
  expect(requests.filter((url) => url.includes('/api/v1/analytics/'))).toEqual([]);
  expect(
    requests.filter((url) => /google-analytics|googletagmanager|doubleclick/i.test(url)),
  ).toEqual([]);
});

test('long tool article and footer remain usable at narrow mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.goto('/tools/structured-data-checker/');
  const sizes = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(sizes.scroll).toBeLessThanOrEqual(sizes.width + 1);
  await expect(page.getByRole('link', { name: 'Privacy', exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: 'Mobile navigation' }).locator('a').first().count();
});
