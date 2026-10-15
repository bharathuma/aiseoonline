import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const tools = [
  { slug: 'robots-txt-validator', kind: 'robots', label: 'Website URL' },
  { slug: 'xml-sitemap-validator', kind: 'sitemap', label: 'XML sitemap URL' },
  { slug: 'meta-tag-checker', kind: 'meta', label: 'Webpage URL' },
  { slug: 'redirect-chain-checker', kind: 'redirects', label: 'Redirect starting URL' },
  { slug: 'canonical-url-checker', kind: 'canonical', label: 'Webpage URL' },
  { slug: 'structured-data-checker', kind: 'schema', label: 'Webpage URL' },
  { slug: 'heading-structure-analyzer', kind: 'headings', label: 'Webpage URL' },
  { slug: 'internal-link-checker', kind: 'links', label: 'Webpage URL' },
  { slug: 'social-metadata-checker', kind: 'social', label: 'Webpage URL' },
] as const;

for (const tool of tools) {
  test(`${tool.kind}: complete public form, inspect evidence and download real JSON`, async ({
    page,
  }) => {
    let requestCount = 0;
    const url =
      tool.kind === 'sitemap' ? 'https://example.org/sitemap.xml' : 'https://example.org/';
    await page.route(`**/api/v1/tools/${tool.kind}`, async (route) => {
      requestCount += 1;
      const submitted = route.request().postDataJSON() as { url: string };
      expect(submitted.url).toBe(url);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tool: tool.kind,
          requested_url: url,
          final_url: url,
          checked_at: '2026-10-15T12:00:00Z',
          facts: { observed_fixture: `${tool.kind}-verified` },
          issues: [
            {
              code: 'fixture.review',
              severity: 'info',
              message: 'Review the observed evidence',
              recommendation: 'Verify the source before making changes.',
              evidence: 'Page response was inspected',
            },
          ],
        }),
      });
    });
    await page.goto(`/tools/${tool.slug}/`);
    await page.getByLabel(tool.label).fill(url);
    await page.getByRole('button', { name: 'Run free check' }).click();
    await expect(page.getByRole('heading', { name: 'Check complete' })).toBeVisible();
    await expect(page.getByText(`${tool.kind}-verified`)).toBeVisible();
    await expect(page.getByText('Review the observed evidence')).toBeVisible();
    expect(requestCount).toBe(1);

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download JSON' }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`${tool.kind}-report.json`);
  });
}

test('public tool recovers after an HTTP failure without stale successful results', async ({
  page,
}) => {
  let attempts = 0;
  await page.route('**/api/v1/tools/robots', async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'service_unavailable', message: 'Checks are temporarily unavailable.' },
          request_id: 'fixture-request',
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'robots',
        requested_url: 'https://example.org/',
        final_url: 'https://example.org/',
        checked_at: '2026-10-15T12:00:00Z',
        facts: { state: 'recovered' },
        issues: [],
      }),
    });
  });
  await page.goto('/tools/robots-txt-validator/');
  await page.getByLabel('Website URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable');
  await expect(page.getByRole('heading', { name: 'Check complete' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('heading', { name: 'Check complete' })).toBeVisible();
  await expect(page.getByText('recovered')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(attempts).toBe(2);
});

test('network interruption leaves controls usable and shows an error', async ({ page }) => {
  await page.route('**/api/v1/tools/meta', async (route) => route.abort('failed'));
  await page.goto('/tools/meta-tag-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run free check' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Check complete' })).toHaveCount(0);
});

test('tool form rejects invalid URL without network calls', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/v1/tools/meta', async (route) => {
    calls += 1;
    await route.abort();
  });
  await page.goto('/tools/meta-tag-checker/');
  await page.getByLabel('Webpage URL').fill('this is not a URL');
  await page.getByRole('button', { name: 'Run free check' }).click();
  expect(calls).toBe(0);
  await expect(page.getByRole('heading', { name: 'Check complete' })).toHaveCount(0);
});

for (const width of [320, 375, 390, 768, 1024]) {
  test(`SEO tool is operable without horizontal viewport overflow at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 760 });
    await page.goto('/tools/meta-tag-checker/');
    await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      bodyWidth: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    expect(dimensions.bodyWidth).toBeLessThanOrEqual(dimensions.viewport + 1);
    await page.getByLabel('Webpage URL').fill('https://example.org/');
    await expect(page.getByLabel('Webpage URL')).toHaveValue('https://example.org/');
  });
}

for (const slug of ['meta-tag-checker', 'xml-sitemap-validator', 'ai-meta-suggestions']) {
  test(`${slug}: no automated WCAG A/AA violations in primary controls`, async ({ page }) => {
    await page.goto(`/tools/${slug}/`);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    expect(
      results.violations.map((item) => ({
        id: item.id,
        target: item.nodes.map((node) => node.target),
      })),
    ).toEqual([]);
  });
}

test('public tool input and submit are usable with keyboard-only navigation', async ({ page }) => {
  await page.goto('/tools/meta-tag-checker/');
  const input = page.getByLabel('Webpage URL');
  await input.focus();
  await expect(input).toBeFocused();
  await page.keyboard.type('https://example.org/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Run free check' })).toBeFocused();
});

test('records headless local-preview navigation timing without claiming field speed', async ({
  page,
}) => {
  for (const slug of ['meta-tag-checker', 'xml-sitemap-validator', 'ai-meta-suggestions']) {
    await page.goto(`/tools/${slug}/`, { waitUntil: 'load' });
    const sample = await page.evaluate(() => {
      const navigation = performance.getEntriesByType('navigation')[0] as
        PerformanceNavigationTiming | undefined;
      return {
        navigation_ms: Math.round(navigation?.duration ?? -1),
        bytes_transferred: Math.round(navigation?.transferSize ?? -1),
      };
    });
    expect(sample.navigation_ms).toBeGreaterThanOrEqual(0);
    console.log(
      'QA_WEB_NAVIGATION|' + JSON.stringify({ slug, environment: 'local-preview', ...sample }),
    );
  }
});
