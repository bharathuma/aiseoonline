import { useMemo, useState } from 'react';
import { filterTools, plannedTools, toolCategories, toolPath } from './toolCatalog';
import type { CategoryFilter } from './toolCatalog';

export default function ToolDirectory() {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<CategoryFilter>('All');
  const results = useMemo(() => filterTools(query, plannedTools, category), [query, category]);

  return (
    <section aria-labelledby="tools-heading" className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <p className="eyebrow">Explore the toolkit</p>
          <h2
            id="tools-heading"
            className="mt-3 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl"
          >
            Find the right check
          </h2>
          <p className="mt-3 leading-7 text-slate-600">
            Try the available free checkers or explore the tools still in development.
          </p>
        </div>
        <span className="status-pill">Free tools · No signup</span>
      </div>

      <form
        className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-[1fr_220px]"
        role="search"
        onSubmit={(event) => event.preventDefault()}
      >
        <div>
          <label htmlFor="tool-search" className="form-label">
            Search tools
          </label>
          <input
            id="tool-search"
            name="q"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Sitemaps, redirects, metadata…"
            className="form-input"
          />
        </div>
        <div>
          <label htmlFor="tool-category" className="form-label">
            Category
          </label>
          <select
            id="tool-category"
            className="form-input"
            value={category}
            onChange={(event) => setCategory(event.target.value as CategoryFilter)}
          >
            <option value="All">All categories</option>
            {toolCategories.map((item) => (
              <option value={item} key={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </form>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" aria-live="polite" aria-atomic="true" className="text-sm text-slate-600">
          {results.length} {results.length === 1 ? 'tool' : 'tools'} found
        </p>
        {(query || category !== 'All') && (
          <button
            type="button"
            className="inline-link text-sm font-semibold"
            onClick={() => {
              setQuery('');
              setCategory('All');
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {results.length > 0 ? (
        <ul className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {results.map((tool) => (
            <li key={tool.id} className="h-full">
              <article className="surface-card group flex h-full flex-col transition-transform duration-200 motion-safe:hover:-translate-y-1">
                <div className="flex items-start justify-between gap-3">
                  <span className="category-label">{tool.category}</span>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                    {tool.status === 'available' ? 'Available' : 'Planned'}
                  </span>
                </div>
                <h3 className="mt-5 text-xl font-semibold tracking-tight text-slate-950">
                  <a href={toolPath(tool)} className="card-link">
                    {tool.name}
                  </a>
                </h3>
                <p className="mt-3 flex-1 text-sm leading-7 text-slate-600">{tool.summary}</p>
                <span className="mt-6 text-sm font-semibold text-teal-800">
                  {tool.status === 'available' ? 'Open free tool' : 'Read about this tool'} <span aria-hidden="true">↗</span>
                </span>
              </article>
            </li>
          ))}
        </ul>
      ) : (
        <div
          role="status"
          className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center"
        >
          <p className="text-lg font-semibold text-slate-900">No matching tools</p>
          <p className="mt-2 text-sm text-slate-600">
            Try another keyword or clear the category filter.
          </p>
          <button
            type="button"
            className="ui-button ui-button-outline mt-5"
            onClick={() => {
              setQuery('');
              setCategory('All');
            }}
          >
            Show all tools
          </button>
        </div>
      )}
    </section>
  );
}
