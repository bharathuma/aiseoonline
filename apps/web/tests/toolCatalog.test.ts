import assert from 'node:assert/strict';
import test from 'node:test';
import {
  filterTools,
  plannedTools,
  toolBySlug,
  toolCategories,
  toolPath,
} from '../src/components/toolCatalog.ts';

test('empty search returns all entries', () => {
  assert.equal(filterTools(' ').length, plannedTools.length);
});

test('search ignores case and surrounding spaces', () => {
  const matches = filterTools('  SITEMAP ');
  assert.equal(matches.length, 1);
  assert.equal(matches[0]?.id, 'sitemap');
});

test('search matches descriptive text and categories', () => {
  assert.ok(filterTools('links').some((tool) => tool.id === 'links'));
  assert.ok(filterTools('technical seo').length > 0);
});

test('unknown search gives an empty array', () => {
  assert.deepEqual(filterTools('not-a-tool'), []);
});

test('search does not mutate the catalog', () => {
  const before = [...plannedTools];
  filterTools('meta');
  assert.deepEqual(plannedTools, before);
});

test('categories filter the catalog independently of keywords', () => {
  const links = filterTools('', plannedTools, 'Links');
  assert.ok(links.length > 0);
  assert.ok(links.every((tool) => tool.category === 'Links'));
});

test('search and category combine and empty results are valid', () => {
  assert.equal(filterTools('canonical', plannedTools, 'Content').length, 0);
  assert.equal(filterTools('canonical', plannedTools, 'Technical SEO').length, 1);
});

test('all planned tools have unique ids, slugs and stable paths', () => {
  const ids = plannedTools.map((tool) => tool.id);
  const slugs = plannedTools.map((tool) => tool.slug);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(new Set(slugs).size, slugs.length);
  assert.equal(plannedTools.filter((tool) => tool.status === 'available').length, 10);
  assert.ok(plannedTools.every((tool) => tool.details.length > 0));
  assert.ok(plannedTools.every((tool) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(tool.slug)));
  assert.ok(plannedTools.every((tool) => toolPath(tool) === '/tools/' + tool.slug + '/'));
});

test('lookup returns a known tool and ignores non-existent paths', () => {
  assert.equal(toolBySlug('robots-txt-validator')?.id, 'robots');
  assert.equal(toolBySlug('not-a-tool'), undefined);
});

test('categories cover the catalog without duplicates', () => {
  assert.equal(new Set(toolCategories).size, toolCategories.length);
  assert.ok(plannedTools.every((tool) => toolCategories.includes(tool.category)));
});
