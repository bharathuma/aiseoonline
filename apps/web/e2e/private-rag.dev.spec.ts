import { expect, test } from '@playwright/test';

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
