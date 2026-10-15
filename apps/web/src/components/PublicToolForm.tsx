import { useState } from 'react';
import type { FormEvent } from 'react';

type ToolKind = 'robots' | 'sitemap' | 'meta';
type Issue = {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  recommendation: string;
  evidence: string;
};
type Result = {
  tool: ToolKind;
  requested_url: string;
  final_url: string;
  checked_at: string;
  facts: Record<string, unknown>;
  issues: Issue[];
};

const defaults: Record<ToolKind, { label: string; example: string; hint: string }> = {
  robots: {
    label: 'Website URL',
    example: 'https://example.org/',
    hint: 'Enter the site address. We check its root /robots.txt file, not a page-specific file.',
  },
  sitemap: {
    label: 'XML sitemap URL',
    example: 'https://example.org/sitemap.xml',
    hint: 'Enter the exact sitemap URL. Linked child sitemaps are not fetched.',
  },
  meta: {
    label: 'Webpage URL',
    example: 'https://example.org/about/',
    hint: 'Enter one public HTML page. We check its title, description, headings and directives.',
  },
};

export default function PublicToolForm({ kind }: { kind: ToolKind }) {
  const [url, setUrl] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const spec = defaults[kind];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setError('');
    setResult(null);
    setCopied(false);
    try {
      const target = new URL(url);
      if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) {
        throw new Error('Enter a public HTTP or HTTPS URL without credentials.');
      }
    } catch (exception) {
      setError(exception instanceof Error && exception.message.startsWith('Enter ')
        ? exception.message : 'Enter a complete public URL such as ' + spec.example);
      return;
    }
    setLoading(true);
    const controller = new AbortController();
    const abort = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/api/v1/tools/' + kind, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
        signal: controller.signal,
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = (data as { error?: { message?: string } }).error?.message;
        throw new Error(message || 'The check could not be completed.');
      }
      const report = data as Result;
      if (!Array.isArray(report.issues) || !report.facts || report.tool !== kind) {
        throw new Error('The server returned an unexpected response. Please try again.');
      }
      setResult(report);
    } catch (exception) {
      setError(exception instanceof Error && exception.name === 'AbortError'
        ? 'The check timed out. Please try again later.'
        : exception instanceof Error ? exception.message : 'The check failed.');
    } finally {
      clearTimeout(abort);
      setLoading(false);
    }
  }

  function exportReport() {
    if (!result) return;
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {
      type: 'application/json',
    }));
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = kind + '-report.json';
    anchor.click();
    URL.revokeObjectURL(objectUrl);
  }

  async function copyReport() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopied(true);
    } catch {
      setError('Copy is unavailable in this browser. Use Download JSON instead.');
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="surface-card" aria-label="Run free SEO check">
        <label htmlFor={'tool-url-' + kind} className="form-label">{spec.label}</label>
        <input id={'tool-url-' + kind} className="form-input" type="url"
          required maxLength={2048} autoComplete="url" spellCheck={false}
          placeholder={spec.example} value={url} disabled={loading}
          onChange={(event) => setUrl(event.target.value)} />
        <p className="mt-3 text-sm leading-6 text-slate-600">{spec.hint}</p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button className="ui-button ui-button-primary" type="submit" disabled={loading}>
            {loading ? 'Checking website…' : 'Run free check'}
          </button>
          <span className="text-xs text-slate-600">No account required · One URL per check</span>
        </div>
      </form>
      <div aria-live="polite" aria-atomic="true">
        {loading && <p role="status" className="rounded-xl bg-teal-50 p-4 font-medium text-teal-900">
          Fetching the requested resource. This can take up to 20 seconds.
        </p>}
        {error && <p role="alert" className="status-notice status-error">{error}</p>}
      </div>
      {result && (
        <section aria-label="SEO check results" className="surface-card space-y-6">
          <div className="flex flex-wrap justify-between gap-4">
            <div>
              <p className="eyebrow">Actual website response</p>
              <h2 className="mt-2 text-2xl font-bold">Check complete</h2>
              <p className="mt-2 break-all text-sm text-slate-600">{result.final_url}</p>
              <p className="mt-1 text-xs text-slate-500">Checked {new Date(result.checked_at).toLocaleString()}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="ui-button ui-button-outline ui-button-small" type="button"
                onClick={copyReport}>{copied ? 'Copied' : 'Copy JSON'}</button>
              <button className="ui-button ui-button-outline ui-button-small" type="button"
                onClick={exportReport}>Download JSON</button>
            </div>
          </div>
          <div>
            <h3 className="text-lg font-bold">Observed information</h3>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              {Object.entries(result.facts).map(([key, value]) => (
                <div key={key} className="min-w-0 rounded-xl bg-slate-50 p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                    {key.replaceAll('_', ' ')}
                  </dt>
                  <dd className="mt-2 break-words text-sm text-slate-900">
                    {Array.isArray(value) ? (value.length ? value.join(', ') : 'None found') :
                      value === null || value === '' ? 'Not found' : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <h3 className="text-lg font-bold">Findings ({result.issues.length})</h3>
            {result.issues.length === 0 ? (
              <p role="status" className="mt-3 rounded-xl bg-teal-50 p-4 text-teal-900">
                No issues found by this checker. It does not guarantee search-engine indexing or rankings.
              </p>
            ) : (
              <ul className="mt-4 space-y-3">
                {result.issues.map((item, index) => (
                  <li key={index} className="rounded-xl border border-slate-200 p-4">
                    <span className="category-label">{item.severity}</span>
                    <h4 className="mt-2 font-semibold text-slate-900">{item.message}</h4>
                    <p className="mt-2 text-sm text-slate-700">{item.recommendation}</p>
                    <p className="mt-2 break-all text-xs text-slate-500">Evidence: {item.evidence}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
