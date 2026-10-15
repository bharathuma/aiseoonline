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

test('tool discovery distinguishes implemented checkers and planned AI tools', async ({ page }) => {
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
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
  await page.goto('/tools/ai-meta-suggestions/');
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Generate three suggestions' })).toBeVisible();
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
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'redirects',
        requested_url: 'https://example.org/old',
        final_url: 'https://example.org/new',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          redirect_count: 1,
          final_status: 200,
          termination: 'completed',
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
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'canonical',
        requested_url: 'https://example.org/page',
        final_url: 'https://example.org/page',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          canonical_count: 2,
          declarations: [
            {
              raw: '/a',
              resolved: 'https://example.org/a',
              classification: 'relative',
              ordinal: 1,
            },
            {
              raw: '/b',
              resolved: 'https://example.org/b',
              classification: 'relative',
              ordinal: 2,
            },
          ],
        },
        issues: [
          {
            code: 'canonical.conflicting',
            severity: 'warning',
            message: 'Conflicting canonical declarations',
            recommendation: 'Use a single preferred canonical URL.',
            evidence: 'link[rel=canonical]#1: /a; link[rel=canonical]#2: /b',
          },
        ],
      }),
    });
  });
  await page.goto('/tools/canonical-url-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/page');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByText('Conflicting canonical declarations')).toBeVisible();
  await expect(page.getByText('"classification": "relative"').first()).toBeVisible();
});

test('schema checker displays types and safely renders malicious-looking evidence', async ({
  page,
}) => {
  await page.route('**/api/v1/tools/schema', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'schema',
        requested_url: 'https://example.org/page',
        final_url: 'https://example.org/page',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          jsonld_blocks: 1,
          parsed_blocks: 1,
          types: ['Article'],
          nodes: [{ evidence: 'script#1', types: ['Article'] }],
        },
        issues: [
          {
            code: 'schema.context_other',
            severity: 'info',
            message: 'A non-schema.org context was declared.',
            recommendation: 'Check the chosen vocabulary.',
            evidence: '<img src=x onerror=alert(1)>',
          },
        ],
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
    'redirect-chain-checker',
    'canonical-url-checker',
    'structured-data-checker',
  ]) {
    await page.goto('/tools/' + slug + '/');
    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
  }
});

test('heading tool shows the real H1–H6 outline in document order', async ({ page }) => {
  await page.route('**/api/v1/tools/headings', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'headings',
        requested_url: 'https://example.org/',
        final_url: 'https://example.org/',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          headings: [
            { level: 1, text: 'Main topic', ordinal: 1 },
            { level: 3, text: 'Subtopic', ordinal: 1 },
          ],
          total: 2,
        },
        issues: [
          {
            code: 'heading.skipped_level',
            severity: 'info',
            message: 'Heading level jump',
            recommendation: 'Review heading structure.',
            evidence: 'h3#1: Subtopic',
          },
        ],
      }),
    });
  });
  await page.goto('/tools/heading-structure-analyzer/');
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await page.getByLabel('Webpage URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('list', { name: 'HTML heading outline' }).locator('li')).toHaveCount(
    2,
  );
  await expect(page.getByText('Heading level jump')).toBeVisible();
});

test('internal-link checker differentiates verified and unchecked results', async ({ page }) => {
  await page.route('**/api/v1/tools/links', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'links',
        requested_url: 'https://example.org/',
        final_url: 'https://example.org/',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          internal_links: 1,
          external_links: 1,
          probed_destinations: 1,
          links: [
            {
              url: 'https://example.org/missing',
              classification: 'internal',
              status: 404,
              state: 'verified',
            },
            {
              url: 'https://external.org/page',
              classification: 'external',
              status: null,
              state: 'not_checked',
            },
          ],
        },
        issues: [
          {
            code: 'links.broken_verified',
            severity: 'error',
            message: 'An internal URL returned a broken-page status.',
            recommendation: 'Update the link.',
            evidence: 'a#1: HTTP 404',
          },
        ],
      }),
    });
  });
  await page.goto('/tools/internal-link-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText('An internal URL returned a broken-page status.')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'not checked' })).toBeVisible();
});

test('social checker labels its preview as approximate and never loads the image', async ({
  page,
}) => {
  await page.route('**/api/v1/tools/social', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tool: 'social',
        requested_url: 'https://example.org/',
        final_url: 'https://example.org/',
        checked_at: '2026-10-15T12:00:00Z',
        facts: {
          approximate_preview: {
            title: 'Sample social title',
            description: 'Shared description',
            site_name: 'Example',
            image_url: 'https://example.org/photo.jpg',
          },
          open_graph: { 'og:title': ['Sample social title'] },
        },
        issues: [],
      }),
    });
  });
  await page.goto('/tools/social-metadata-checker/');
  await page.getByLabel('Webpage URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Run free check' }).click();
  const preview = page.getByLabel('Approximate social sharing preview');
  await expect(preview.getByText('Sample social title')).toBeVisible();
  await expect(preview.getByText(/Approximate preview/)).toBeVisible();
  await expect(preview.locator('img')).toHaveCount(0);
});

test('all nine deterministic tools have indexable pages and working controls', async ({ page }) => {
  for (const slug of [
    'robots-txt-validator',
    'xml-sitemap-validator',
    'meta-tag-checker',
    'redirect-chain-checker',
    'canonical-url-checker',
    'structured-data-checker',
    'heading-structure-analyzer',
    'internal-link-checker',
    'social-metadata-checker',
  ]) {
    await page.goto('/tools/' + slug + '/');
    await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Run free check' })).toBeVisible();
  }
});

test('AI meta tool accepts pasted input and displays three editable suggestions', async ({
  page,
}) => {
  await page.route('**/api/v1/tools/ai-meta', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source_type: 'text',
        source_url: null,
        source_summary: 'Visitor-provided text',
        model: 'fixture',
        checked_at: '2026-10-15T12:00:00Z',
        cached: false,
        usage: { input_tokens: 120, output_tokens: 160, total_tokens: 280 },
        estimated_cost_usd: '0.00018',
        visitor_message: 'Three AI drafts generated.',
        suggestions: Array.from({ length: 3 }, (_, i) => ({
          title: 'Handmade planters from natural clay ' + i,
          description:
            'Explore handmade planters for houseplants with simple indoor care advice ' + i,
          evidence_quote: 'Handmade planters',
          rationale: 'Observed source content',
          warnings: ['Verify facts before use'],
          title_characters: 40,
          description_characters: 80,
        })),
      }),
    });
  });
  await page.goto('/tools/ai-meta-suggestions/');
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: /AI title & meta description generator/ }),
  ).toBeVisible();
  await page
    .getByLabel('Your page content')
    .fill(
      'Our independent pottery studio makes handmade planters from natural clay. ' +
        'We make small plant pots and publish simple indoor plant care tips for beginners. ' +
        'Our studio focuses on indoor houseplants and practical planter selection.',
    );
  await page.getByRole('button', { name: 'Generate three suggestions' }).click();
  await expect(page.getByRole('heading', { name: 'Suggestion 3' })).toBeVisible();
  await expect(page.getByText('Measured tokens: 280.')).toBeVisible();
  const title = page.getByLabel('Editable SEO title').first();
  await title.fill('An editable title for my page');
  await expect(title).toHaveValue('An editable title for my page');
  await expect(page.getByText('Warnings apply to the original AI draft').first()).toBeVisible();
});

test('AI generator shows an actionable unavailable-credentials error', async ({ page }) => {
  await page.route('**/api/v1/tools/ai-meta', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: {
          code: 'ai_not_configured',
          message: 'AI suggestions are not currently available.',
        },
      }),
    });
  });
  await page.goto('/tools/ai-meta-suggestions/');
  await page.getByLabel('Fetch public URL').check();
  await page.getByLabel('Public page URL').fill('https://example.org/');
  await page.getByRole('button', { name: 'Generate three suggestions' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'AI suggestions are not currently available.',
  );
  await expect(page.getByRole('link', { name: /Try the free Meta Tag Checker/ })).toBeVisible();
});

test('AI generator rejects short pasted content without contacting backend', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/v1/tools/ai-meta', async (route) => {
    calls++;
    await route.abort();
  });
  await page.goto('/tools/ai-meta-suggestions/');
  await page.getByLabel('Your page content').fill('too short');
  await page.getByRole('button', { name: 'Generate three suggestions' }).click();
  await expect(page.getByLabel('Your page content')).toHaveAttribute('minlength', '100');
  await expect(page.getByRole('heading', { name: 'Suggestion 1' })).toHaveCount(0);
  expect(calls).toBe(0);
});

test('development-only RAG chat displays linked evidence and bounded follow-up', async ({
  page,
}) => {
  const project = 'b0aa11c1-5f4b-4d02-8be9-087ea6d98220';
  const source = 'finding:b0aa11c1-5f4b-4d02-8be9-087ea6d98221';
  const sent: unknown[] = [];
  await page.route('**/api/v1/internal/rag/chat', async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project,
        statements: [
          {
            statement: 'The shop page has no meta description.',
            source_id: source,
            supporting_quote: 'Missing meta description',
          },
        ],
        sources: [
          {
            source_id: source,
            kind: 'seo_finding',
            source_url: 'https://example.org/shop',
            section_heading: null,
            captured_at: '2026-10-15T10:00:00Z',
            excerpt: 'description.missing: Missing meta description',
          },
        ],
        uncertainty: 'Other pages have not been audited.',
        evidence_scope: 'Only recorded findings and indexed excerpts.',
        model: 'offline-test',
      }),
    });
  });
  await page.goto('/internal/rag-chat/');
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex,follow');
  await page.getByLabel('Verified project UUID').fill(project);
  await page.getByLabel('Development access token').fill('123456789012345678901234567890123456');
  await page.getByLabel('Your question').fill('Which pages lack meta descriptions?');
  await page.getByRole('button', { name: 'Ask about this project' }).click();
  await expect(page.getByText('The shop page has no meta description.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'https://example.org/shop' })).toHaveAttribute(
    'href',
    'https://example.org/shop',
  );
  await expect(page.getByText('Other pages have not been audited.')).toBeVisible();
  await page.getByLabel('Your question').fill('What evidence supports the issue?');
  await page.getByRole('button', { name: 'Ask about this project' }).click();
  await expect.poll(() => sent.length).toBe(2);
  expect((sent[1] as { previous_questions: string[] }).previous_questions).toEqual([
    'Which pages lack meta descriptions?',
  ]);
  await page.getByRole('button', { name: 'Clear this conversation' }).click();
  await expect(page.getByText('The shop page has no meta description.')).toHaveCount(0);
});

test('private assistant access errors do not reveal project data', async ({ page }) => {
  await page.route('**/api/v1/internal/rag/chat', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'not_found', message: 'The requested resource was not found.' },
      }),
    });
  });
  await page.goto('/internal/rag-chat/');
  await page.getByLabel('Verified project UUID').fill('b0aa11c1-5f4b-4d02-8be9-087ea6d98220');
  await page.getByLabel('Development access token').fill('123456789012345678901234567890123456');
  await page.getByLabel('Your question').fill('What are the biggest SEO issues?');
  await page.getByRole('button', { name: 'Ask about this project' }).click();
  await expect(page.getByRole('alert')).toContainText('The requested resource was not found.');
  await expect(page.getByText('The shop page has no meta description.')).toHaveCount(0);
});
