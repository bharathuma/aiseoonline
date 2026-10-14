import assert from 'node:assert/strict';
import test from 'node:test';
import { filterTools, plannedTools } from '../src/components/toolCatalog.ts';

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
