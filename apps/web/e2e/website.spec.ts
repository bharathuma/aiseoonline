import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('homepage renders useful content, metadata and working navigation', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Find the issues/i })).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    'https://aiseoonline.com/',
  );
  await expect(page.locator('meta[property="og:description"]')).toHaveAttribute(
    'content',
    /SEO utilities|technical checks/i,
  );
  await page
    .getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('link', { name: 'Guides' })
    .click();
  await expect(page).toHaveURL(/\/guides\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('SEO concepts');
});

test('tool discovery searches and filters without pretending tools are live', async ({ page }) => {
  await page.goto('/tools/');
  await page.getByRole('searchbox', { name: 'Search tools' }).fill('sitemap');
  await expect(page.getByRole('status').filter({ hasText: '1 tool found' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'XML sitemap validator' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search tools' }).fill('');
  await page.getByLabel('Category').selectOption('Links');
  await expect(page.getByRole('heading', { name: 'Internal link checker' })).toBeVisible();
  await page.getByRole('heading', { name: 'Internal link checker' }).getByRole('link').click();
  await expect(
    page.getByRole('heading', { name: 'Internal link checker', level: 1 }),
  ).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex,follow');
  await expect(
    page.getByText('This tool is being developed and cannot run checks yet.'),
  ).toBeVisible();
});

test('dialog opens, closes with Escape and restores keyboard focus', async ({ page }) => {
  await page.goto('/audit/');
  const trigger = page.getByRole('button', { name: 'How will it work?' });
  await trigger.click();
  await expect(page.getByRole('dialog', { name: 'How the audit is designed' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'How the audit is designed' })).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('components page explicitly labels UI state examples', async ({ page }) => {
  await page.goto('/docs/components/');
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex,follow');
  await expect(page.getByText('Error example')).toBeVisible();
  await expect(page.getByText('Success example')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Unavailable action' })).toBeDisabled();
});

for (const width of [375, 768, 1440]) {
  test('homepage remains within viewport at ' + width + 'px', async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      pageWidth: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewport + 1);
    await page.screenshot({
      path: 'test-results/screenshots/home-' + width + '.png',
      fullPage: true,
    });
  });
}

test('homepage has no common WCAG A/AA violations', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map((item) => ({ id: item.id, nodes: item.nodes.map((n) => n.target) })),
  ).toEqual([]);
});

test('mobile navigation works with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto('/');
  const menu = page.locator('summary.mobile-menu-summary');
  await menu.focus();
  await page.keyboard.press('Enter');
  const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' });
  await expect(mobileNav).toBeVisible();
  await mobileNav.getByRole('link', { name: 'Documentation' }).click();
  await expect(page).toHaveURL(/\/docs\/$/);
});

test('meta checker submits input and displays evidence from API', async ({ page }) => {
  await page.route('**/api/v1/tools/meta', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'meta',
        requested_url: 'https://example.org/',
        final_url: 'https://example.org/',
        checked_at: '2026-10-15T12:00:00Z',
        facts: { title: 'Fixture title', descriptions: ['Real page text'] },
        issues: [
          {
            code: 'title.length',
            severity: 'info',
            message: 'Review page title length',
            recommendation: 'Write a descriptive title.',
            evidence: 'title#1: Fixture title',
          },
        ],
      }),
    });
  });
  await page.goto('/tools/meta-tag-checker/');
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await page.getByLabel('Webpage URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByText('Fixture title', { exact: true })).toBeVisible();
  await expect(page.getByText('Review page title length')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download JSON' })).toBeVisible();
});

test('public checker surfaces quota errors without claiming success', async ({ page }) => {
  await page.route('**/api/v1/tools/robots', async (route) => {
    await route.fulfill({
      status: 429,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'rate_limited', message: 'Too many checks. Try again later.' },
        request_id: 'abc',
      }),
    });
  });
  await page.goto('/tools/robots-txt-validator/');
  await page.getByLabel('Website URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('alert')).toContainText('Too many checks.');
  await expect(page.getByRole('heading', { name: 'Check complete' })).toHaveCount(0);
});

test('all three live tool pages are indexable and have forms', async ({ page }) => {
  for (const slug of ['robots-txt-validator', 'xml-sitemap-validator', 'meta-tag-checker']) {
    await page.goto('/tools/' + slug + '/');
    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
  }
});


test('redirect checker renders HTTP hops from a real API-shaped result', async ({ page }) => {
  await page.route('**/api/v1/tools/redirects', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        tool: 'redirects', requested_url: 'https://example.org/old',
        final_url: 'https://example.org/new', checked_at: '2026-10-15T12:00:00Z',
        facts: {
          redirect_count: 1, final_status: 200, termination: 'completed',
          hops: [
            { url: 'https://example.org/old', status: 301, location: 'https://example.org/new' },
            { url: 'https://example.org/new', status: 200, location: null },
          ],
        },
        issues: [],
      }),
    });
  });
  await page.goto('/tools/redirect-chain-checker/');
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await page.getByLabel('Redirect starting URL').fill('https://example.org/old');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByText('"status": 301')).toBeVisible();
  await expect(page.getByText('https://example.org/new', { exact: true }).first()).toBeVisible();
});

test('canonical checker displays source evidence for conflicting links', async ({ page }) => {
  await page.route('**/api/v1/tools/canonical', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        tool: 'canonical', requested_url: 'https://example.org/page',
        final_url: 'https://example.org/page', checked_at: '2026-10-15T12:00:00Z',
        facts: { canonical_count: 2, declarations: [
          { raw: '/a', resolved: 'https://example.org/a', classification: 'relative', ordinal: 1 },
          { raw: '/b', resolved: 'https://example.org/b', classification: 'relative', ordinal: 2 },
        ] },
        issues: [{
          code: 'canonical.conflicting', severity: 'warning',
          message: 'Conflicting canonical declarations',
          recommendation: 'Use a single preferred canonical URL.',
          evidence: 'link[rel=canonical]#1: /a; link[rel=canonical]#2: /b',
        }],
      }),
    });
  });
  await page.goto('/tools/canonical-url-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/page');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByText('Conflicting canonical declarations')).toBeVisible();
  await expect(page.getByText('"classification": "relative"').first()).toBeVisible();
});

test('schema checker displays types and safely renders malicious-looking evidence', async ({ page }) => {
  await page.route('**/api/v1/tools/schema', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        tool: 'schema', requested_url: 'https://example.org/page',
        final_url: 'https://example.org/page', checked_at: '2026-10-15T12:00:00Z',
        facts: { jsonld_blocks: 1, parsed_blocks: 1, types: ['Article'],
          nodes: [{ evidence: 'script#1', types: ['Article'] }] },
        issues: [{
          code: 'schema.context_other', severity: 'info',
          message: 'A non-schema.org context was declared.',
          recommendation: 'Check the chosen vocabulary.', evidence: '<img src=x onerror=alert(1)>',
        }],
      }),
    });
  });
  await page.goto('/tools/structured-data-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/page');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByText('"Article"').first()).toBeVisible();
  await expect(page.getByText('A non-schema.org context was declared.')).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
});

test('new tool pages are indexable and expose controls', async ({ page }) => {
  for (const slug of [
    'redirect-chain-checker', 'canonical-url-checker', 'structured-data-checker',
  ]) {
    await page.goto('/tools/' + slug + '/');
    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
  }
});
