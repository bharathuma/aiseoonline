import { useMemo, useState } from 'react';
import { filterTools } from './toolCatalog';

export default function ToolDirectory() {
  const [query, setQuery] = useState('');
  const results = useMemo(() => filterTools(query), [query]);

  return (
    <section aria-labelledby="tools-heading" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-widest text-teal-700">Tool directory</p>
          <h2 id="tools-heading" className="mt-2 text-2xl font-semibold text-slate-900">What we're building</h2>
          <p className="mt-2 max-w-2xl text-slate-600">Browse the planned tools. They will be enabled as they're released.</p>
        </div>
        <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-sm text-amber-800">In development</span>
      </div>
      <div className="max-w-lg">
        <label htmlFor="tool-search" className="mb-2 block text-sm font-medium text-slate-800">Search planned tools</label>
        <input id="tool-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try sitemap, links, titles..." className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-900 outline-offset-4 placeholder:text-slate-400 focus:border-teal-700 focus:outline-2 focus:outline-teal-700" />
      </div>
      <p aria-live="polite" className="text-sm text-slate-500">{results.length} planned {results.length === 1 ? 'tool' : 'tools'} found</p>
      {results.length ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {results.map((tool) => (
            <li key={tool.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-teal-700">{tool.category}</span>
              <h3 className="mt-2 text-lg font-semibold text-slate-900">{tool.name}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{tool.summary}</p>
              <p className="mt-4 text-xs font-medium text-slate-500">Planned</p>
            </li>
          ))}
        </ul>
      ) : (
        <p role="status" className="rounded-xl border border-slate-200 bg-white p-5 text-slate-600">No planned tools match your search.</p>
      )}
    </section>
  );
}
