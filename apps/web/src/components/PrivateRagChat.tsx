import { useState } from 'react';
import type { FormEvent } from 'react';

type Source = {
  source_id: string;
  kind: 'indexed_page' | 'seo_finding';
  source_url: string;
  section_heading: string | null;
  captured_at: string;
  excerpt: string;
};
type Answer = {
  project_id: string;
  statements: { statement: string; source_id: string; supporting_quote: string }[];
  sources: Source[];
  uncertainty: string;
  evidence_scope: string;
  model: string | null;
};
type Exchange = { question: string; answer: Answer };

function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    if (url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export default function PrivateRagChat() {
  const [projectId, setProjectId] = useState('');
  const [token, setToken] = useState('');
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<Exchange[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const currentQuestion = question.trim();
    if (currentQuestion.length < 8) {
      setError('Ask a question with at least 8 characters.');
      return;
    }
    setBusy(true);
    setError('');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 55000);
    try {
      const response = await fetch('/api/v1/internal/rag/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Dev-Rag-Token': token,
        },
        body: JSON.stringify({
          project_id: projectId.trim(),
          question: currentQuestion,
          previous_questions: history.slice(-3).map((entry) => entry.question),
        }),
        signal: controller.signal,
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        const issue = (payload as { error?: { message?: string } }).error?.message;
        throw new Error(issue || 'The private assistant could not answer this question.');
      }
      const result = payload as Answer;
      if (
        !Array.isArray(result.statements) ||
        !Array.isArray(result.sources) ||
        typeof result.uncertainty !== 'string'
      ) {
        throw new Error('The server returned an invalid evidence response.');
      }
      setHistory((items) => [...items.slice(-5), { question: currentQuestion, answer: result }]);
      setQuestion('');
    } catch (problem) {
      const message = problem instanceof Error ? problem.message : 'The request failed.';
      setError(
        problem instanceof Error && problem.name === 'AbortError'
          ? 'The request timed out. Please try again.'
          : message,
      );
    } finally {
      clearTimeout(timeout);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="surface-card space-y-4">
        <p className="text-sm font-semibold text-amber-900">Local development access only</p>
        <p className="text-sm text-slate-700">
          Chat is unavailable in production. Use a locally verified project, your temporary
          development token, and the backend owner identity configured in your environment. Neither
          your token nor conversation history is saved in browser storage.
        </p>
        <div>
          <label className="form-label" htmlFor="rag-project">
            Verified project UUID
          </label>
          <input
            id="rag-project"
            className="form-input"
            required
            placeholder="00000000-0000-0000-0000-000000000000"
            value={projectId}
            maxLength={36}
            onChange={(event) => {
              setProjectId(event.target.value);
              setHistory([]);
            }}
          />
        </div>
        <div>
          <label className="form-label" htmlFor="rag-token">
            Development access token
          </label>
          <input
            id="rag-token"
            className="form-input"
            required
            type="password"
            autoComplete="off"
            minLength={32}
            maxLength={256}
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <p className="mt-2 text-xs text-slate-600">
            The token is sent to the local API in a custom header; do not enter a production secret.
          </p>
        </div>
      </div>
      <section className="space-y-4" aria-label="Private RAG conversation">
        <div aria-live="polite" className="space-y-5">
          {history.length === 0 && (
            <div className="surface-card">
              <h2 className="text-lg font-bold">Ask about collected website evidence</h2>
              <p className="mt-2 text-sm text-slate-700">
                Example: Which indexed pages have missing meta descriptions? Answers cite stored
                snapshots or completed audit findings. If your project has no qualifying evidence,
                the assistant will say so.
              </p>
            </div>
          )}
          {history.map((exchange, index) => {
            const sources = new Map(exchange.answer.sources.map((item) => [item.source_id, item]));
            return (
              <article className="surface-card space-y-4" key={index}>
                <h2 className="text-base font-semibold">You asked: {exchange.question}</h2>
                {exchange.answer.statements.length === 0 && (
                  <p className="text-slate-700">
                    No supported conclusions from the available evidence.
                  </p>
                )}
                <ol className="list-decimal space-y-4 pl-5">
                  {exchange.answer.statements.map((statement, i) => {
                    const source = sources.get(statement.source_id);
                    const url = source ? safeSourceUrl(source.source_url) : null;
                    return (
                      <li key={i} className="space-y-2 text-sm text-slate-800">
                        <p>{statement.statement}</p>
                        {source && (
                          <div className="rounded-lg border border-slate-200 p-3">
                            <p className="text-xs font-semibold text-slate-600">
                              Evidence {i + 1} ·{' '}
                              {source.kind === 'seo_finding'
                                ? 'Recorded SEO finding'
                                : 'Indexed page excerpt'}
                            </p>
                            <blockquote className="mt-1 break-words text-slate-700">
                              “{statement.supporting_quote}”
                            </blockquote>
                            {url ? (
                              <a
                                className="inline-link mt-2 block break-all"
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {source.section_heading || source.source_url}
                              </a>
                            ) : (
                              <span className="mt-2 block break-all text-xs">
                                {source.source_url}
                              </span>
                            )}
                            <p className="mt-1 break-all text-xs text-slate-500">
                              {source.source_id}
                            </p>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
                {exchange.answer.uncertainty && (
                  <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
                    What remains unknown: {exchange.answer.uncertainty}
                  </p>
                )}
                <p className="text-xs text-slate-600">{exchange.answer.evidence_scope}</p>
              </article>
            );
          })}
        </div>
        <form className="surface-card space-y-4" onSubmit={ask} aria-label="Ask private assistant">
          <label className="form-label" htmlFor="rag-question">
            Your question
          </label>
          <textarea
            id="rag-question"
            className="form-input"
            rows={3}
            required
            minLength={8}
            maxLength={500}
            value={question}
            disabled={busy}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="What evidence supports the highest-priority SEO issue?"
          />
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" disabled={busy} className="ui-button ui-button-primary">
              {busy ? 'Checking evidence…' : 'Ask about this project'}
            </button>
            <button
              type="button"
              className="ui-button ui-button-outline"
              disabled={busy || history.length === 0}
              onClick={() => {
                setHistory([]);
                setError('');
              }}
            >
              Clear this conversation
            </button>
          </div>
          <p className="text-xs text-slate-600">
            Only your last three questions are sent for follow-up context; previous answers are
            never treated as factual evidence. Sources are collected again for every question.
          </p>
          {error && (
            <p role="alert" className="status-notice status-error">
              {error}
            </p>
          )}
          {busy && (
            <p role="status" className="text-sm text-teal-800">
              Retrieving authorized evidence and validating citations…
            </p>
          )}
        </form>
      </section>
    </div>
  );
}
