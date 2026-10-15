import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('homepage renders useful content, metadata and working navigation', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Find the issues/i })).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', 'https://aiseoonline.com/');
  await expect(page.locator('meta[property="og:description"]')).toHaveAttribute('content', /SEO utilities|technical checks/i);
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Guides' }).click();
  await expect(page).toHaveURL(/\/guides\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('SEO concepts');
});

test('tool discovery searches and filters without pretending tools are live', async ({ page }) => {
  await page.goto('/tools/');
  await page.getByRole('searchbox', { name: 'Search tools' }).fill('sitemap');
  await expect(page.getByRole('status').filter({ hasText: '1 planned tool found' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'XML sitemap validator' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search tools' }).fill('');
  await page.getByLabel('Category').selectOption('Links');
  await expect(page.getByRole('heading', { name: 'Internal link checker' })).toBeVisible();
  await page.getByRole('heading', { name: 'Internal link checker' }).getByRole('link').click();
  await expect(page.getByRole('heading', { name: 'Internal link checker', level: 1 })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex,follow');
  await expect(page.getByText('This tool is being developed and cannot run checks yet.')).toBeVisible();
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
      viewport: document.documentElement.clientWidth
    }));
    expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewport + 1);
    await page.screenshot({ path: 'test-results/screenshots/home-' + width + '.png', fullPage: true });
  });
}

test('homepage has no common WCAG A/AA violations', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(results.violations.map((item) => ({ id: item.id, nodes: item.nodes.map((n) => n.target) }))).toEqual([]);
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
