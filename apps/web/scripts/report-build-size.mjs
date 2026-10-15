import { readdir, stat } from 'node:fs/promises';
import { join, relative, resolve } from 'node:path';

const dist = resolve('apps/web/dist');

async function enumerate(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolute = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await enumerate(absolute)));
    else if (entry.isFile()) {
      const file = await stat(absolute);
      files.push({ path: relative(dist, absolute).replaceAll('\\', '/'), bytes: file.size });
    }
  }
  return files;
}

const files = await enumerate(dist);
const html = files.filter((file) => file.path.endsWith('.html'));
const scripts = files.filter((file) => file.path.endsWith('.js'));
const css = files.filter((file) => file.path.endsWith('.css'));
const mainPage = files.find((file) => file.path === 'tools/meta-tag-checker/index.html');
if (!mainPage || !html.length || !scripts.length) {
  throw new Error('Expected static tool page or JavaScript assets were not emitted.');
}
const size = (items) => items.reduce((total, item) => total + item.bytes, 0);
const summary = {
  environment: 'Astro build, uncompressed disk bytes',
  html_files: html.length,
  js_files: scripts.length,
  js_total_bytes: size(scripts),
  css_total_bytes: size(css),
  largest_js_bytes: Math.max(...scripts.map((file) => file.bytes)),
  meta_tool_html_bytes: mainPage.bytes,
};
console.log('QA_WEB_BUILD|' + JSON.stringify(summary));
