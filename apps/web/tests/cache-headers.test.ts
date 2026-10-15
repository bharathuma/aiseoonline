import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('static hosting revalidates HTML but strongly caches fingerprinted assets', () => {
  const headers = readFileSync('public/_headers', 'utf8');
  assert.match(headers, /\/\*\s+Cache-Control: public, max-age=0, must-revalidate/);
  assert.match(headers, /\/_astro\/\*\s+Cache-Control: public, max-age=31536000, immutable/);
  assert.match(headers, /X-Content-Type-Options: nosniff/);
});
