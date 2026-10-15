import { useState } from 'react';
import type { FormEvent } from 'react';

type Choice = {
  title: string;
  description: string;
  evidence_quote: string;
  rationale: string;
  title_characters: number;
  description_characters: number;
  warnings: string[];
};
type Report = {
  suggestions: Choice[];
  source_type: 'url' | 'text';
  source_url: string | null;
  source_summary: string;
  model: string;
  cached: boolean;
  checked_at: string;
  usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  estimated_cost_usd: string | null;
  visitor_message: string;
};
type Editable = { title: string; description: string };

function rangeHint(length: number, low: number, high: number) {
  return length < low
    ? 'Shorter than the advisory range'
    : length > high
      ? 'Longer than the advisory range'
      : 'Within the advisory range';
}

export default function AiMetaForm() {
  const [mode, setMode] = useState<'url' | 'text'>('text');
  const [url, setUrl] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [drafts, setDrafts] = useState<Editable[]>([]);
  const [copyState, setCopyState] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setError('');
    setReport(null);
    setDrafts([]);
    setCopyState('');
    if (mode === 'text' && content.trim().length < 100) {
      setError('Paste at least 100 characters of your own page content.');
      return;
    }
    if (mode === 'url') {
      try {
        const parsed = new URL(url);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password)
          throw new Error();
      } catch {
        setError('Enter a full public HTTP or HTTPS URL without credentials.');
        return;
      }
    }
    setLoading(true);
    const controller = new AbortController();
    const abort = setTimeout(() => controller.abort(), 58000);
    try {
      const response = await fetch('/api/v1/tools/ai-meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'url' ? { url } : { content }),
        signal: controller.signal,
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = (data as { error?: { message?: string } }).error?.message;
        throw new Error(message || 'This AI check is unavailable. Please try again later.');
      }
      const value = data as Report;
      if (
        !Array.isArray(value.suggestions) ||
        value.suggestions.length !== 3 ||
        !value.suggestions.every(
          (item) =>
            typeof item.title === 'string' &&
            typeof item.description === 'string' &&
            Array.isArray(item.warnings),
        )
      ) {
        throw new Error('Unexpected AI response. No suggestions were accepted.');
      }
      setReport(value);
      setDrafts(value.suggestions.map(({ title, description }) => ({ title, description })));
    } catch (exception) {
      setError(
        exception instanceof Error && exception.name === 'AbortError'
          ? 'Generation timed out. Try again later, or use the free Meta Tag Checker.'
          : exception instanceof Error
            ? exception.message
            : 'Generation is unavailable.',
      );
    } finally {
      clearTimeout(abort);
      setLoading(false);
    }
  }

  async function copy(index: number, field: keyof Editable) {
    try {
      await navigator.clipboard.writeText(drafts[index][field]);
      setCopyState(index + ':' + field);
    } catch {
      setError('Clipboard access is unavailable. Select the text to copy manually.');
    }
  }

  function edit(index: number, field: keyof Editable, value: string) {
    setDrafts((current) =>
      current.map((item, i) => (i === index ? { ...item, [field]: value } : item)),
    );
    setCopyState('');
  }

  return (
    <div className="space-y-7">
      <form onSubmit={submit} className="surface-card space-y-5" aria-label="AI metadata generator">
        <fieldset className="space-y-3">
          <legend className="form-label">Choose your source</legend>
          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="source"
                checked={mode === 'text'}
                disabled={loading}
                onChange={() => setMode('text')}
              />{' '}
              Paste page content
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="source"
                checked={mode === 'url'}
                disabled={loading}
                onChange={() => setMode('url')}
              />{' '}
              Fetch public URL
            </label>
          </div>
        </fieldset>
        {mode === 'url' ? (
          <div>
            <label className="form-label" htmlFor="ai-page-url">
              Public page URL
            </label>
            <input
              id="ai-page-url"
              type="url"
              required
              autoComplete="url"
              className="form-input"
              maxLength={2048}
              disabled={loading}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.org/article/"
            />
            <p className="mt-2 text-sm text-slate-600">
              Reads the public page title, descriptions and headings only. JavaScript-rendered text
              and private pages are not supported.
            </p>
          </div>
        ) : (
          <div>
            <label className="form-label" htmlFor="ai-page-content">
              Your page content
            </label>
            <textarea
              id="ai-page-content"
              required
              minLength={100}
              maxLength={3000}
              rows={8}
              disabled={loading}
              className="form-input"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="Describe the actual page, its products or services and relevant facts..."
            />
            <p className="mt-2 text-sm text-slate-600">
              {content.length}/3000 characters · Minimum 100. Do not include secrets or personal
              information. Pasted content is not cached.
            </p>
          </div>
        )}
        <button className="ui-button ui-button-primary" type="submit" disabled={loading}>
          {loading ? 'Generating grounded suggestions…' : 'Generate three suggestions'}
        </button>
        <p className="text-xs leading-5 text-slate-600">
          No signup. Requests are limited to three per hour per visitor and a shared daily AI
          spending allocation. Suggestions may be unavailable when funding or service access is
          exhausted.
        </p>
      </form>

      <div aria-live="polite" aria-atomic="true">
        {loading && (
          <p role="status" className="rounded-xl bg-teal-50 p-4 text-teal-900">
            Reviewing your source and generating three drafts. This may take up to a minute.
          </p>
        )}
        {error && (
          <div role="alert" className="status-notice status-error">
            {error}{' '}
            <a className="inline-link" href="/tools/meta-tag-checker/">
              Try the free Meta Tag Checker.
            </a>
          </div>
        )}
      </div>

      {report && (
        <section className="space-y-5" aria-label="AI metadata suggestions">
          <div className="surface-card">
            <h2 className="text-xl font-bold">Three suggestions for your review</h2>
            <p className="mt-2 text-sm text-slate-700">{report.visitor_message}</p>
            <p className="mt-2 text-xs text-slate-600">
              Source: {report.source_summary}.{' '}
              {report.cached ? 'Cached response' : 'New AI response'}.
              {report.usage ? ' Measured tokens: ' + report.usage.total_tokens + '.' : ''}
              {report.estimated_cost_usd
                ? ' Estimated provider cost: $' + report.estimated_cost_usd + '.'
                : ''}
            </p>
            <p className="mt-3 text-sm text-slate-600">
              Character ranges are editorial starting points, not pixel-width or search-engine
              display guarantees. AI may still invent claims. Review every draft before use.
            </p>
          </div>
          {drafts.map((draft, index) => (
            <article className="surface-card space-y-4" key={index}>
              <h3 className="text-lg font-bold">Suggestion {index + 1}</h3>
              <div>
                <label className="form-label" htmlFor={'draft-title-' + index}>
                  Editable SEO title
                </label>
                <input
                  id={'draft-title-' + index}
                  className="form-input"
                  maxLength={160}
                  value={draft.title}
                  onChange={(event) => edit(index, 'title', event.target.value)}
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-slate-600">
                    {draft.title.length} characters · {rangeHint(draft.title.length, 30, 60)}
                  </p>
                  <button
                    type="button"
                    className="ui-button ui-button-outline ui-button-small"
                    onClick={() => copy(index, 'title')}
                  >
                    {copyState === index + ':title' ? 'Copied' : 'Copy title'}
                  </button>
                </div>
              </div>
              <div>
                <label className="form-label" htmlFor={'draft-description-' + index}>
                  Editable meta description
                </label>
                <textarea
                  id={'draft-description-' + index}
                  className="form-input"
                  rows={4}
                  maxLength={320}
                  value={draft.description}
                  onChange={(event) => edit(index, 'description', event.target.value)}
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-slate-600">
                    {draft.description.length} characters ·{' '}
                    {rangeHint(draft.description.length, 70, 160)}
                  </p>
                  <button
                    type="button"
                    className="ui-button ui-button-outline ui-button-small"
                    onClick={() => copy(index, 'description')}
                  >
                    {copyState === index + ':description' ? 'Copied' : 'Copy description'}
                  </button>
                </div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs font-semibold text-slate-700">
                  Source evidence (original draft)
                </p>
                <blockquote className="mt-2 break-words text-sm text-slate-800">
                  {report.suggestions[index].evidence_quote}
                </blockquote>
                <p className="mt-2 text-xs text-slate-600">{report.suggestions[index].rationale}</p>
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-900">
                  {report.suggestions[index].warnings.map((warning, j) => (
                    <li key={j}>{warning}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-slate-600">
                  Warnings apply to the original AI draft; editing is not automatically rechecked.
                </p>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
