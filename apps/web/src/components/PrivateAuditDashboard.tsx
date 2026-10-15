import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

type AuditStatus = {
  id: string;
  status: string;
  progress_step: string;
  progress_percent: number;
  attempts: number;
  cancel_requested: boolean;
  report_ready: boolean;
  error_code: string | null;
};
type Finding = {
  finding_id: string; severity: string; summary: string; affected_url: string;
  evidence_quote: string; evidence_ref: string; correction: string;
};
type Recommendation = { finding_id: string; affected_url: string; advice: string;
  supporting_quote: string; requires_human_approval: boolean };
type Report = {
  status: string;
  findings: Finding[];
  recommendations: Recommendation[];
  uncertainty: string;
  scope: string;
};
const FINISHED = ['completed', 'partial', 'insufficient_evidence', 'cancelled', 'failed', 'timed_out'];

export default function PrivateAuditDashboard() {
  const [token, setToken] = useState('');
  const [projectId, setProjectId] = useState('');
  const [url, setUrl] = useState('');
  const [key, setKey] = useState('');
  const [job, setJob] = useState<AuditStatus | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const current = useRef('');

  function headers(extra: Record<string, string> = {}) {
    return { 'x-dev-audit-token': token, ...extra };
  }

  async function api(path: string, options: RequestInit = {}) {
    const response = await fetch('/api/v1/internal/audits' + path, {
      ...options, headers: headers(options.headers as Record<string, string> | undefined),
      cache: 'no-store',
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const message = data?.error?.message || 'Audit request unavailable.';
      throw new Error(message);
    }
    return response;
  }

  useEffect(() => {
    if (!job || FINISHED.includes(job.status) || !token) return;
    const id = job.id;
    const timer = window.setInterval(async () => {
      if (current.current !== id) return;
      try {
        const response = await api('/' + encodeURIComponent(id));
        const state = await response.json() as AuditStatus;
        if (current.current === id) setJob(state);
      } catch {
        if (current.current === id) setError('Unable to refresh progress. Try again.');
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, token]);

  useEffect(() => {
    if (!job?.report_ready || !token) return;
    let stopped = false;
    api('/' + encodeURIComponent(job.id) + '/report').then(async (response) => {
      const value = await response.json() as Report;
      if (!stopped) setReport(value);
    }).catch(() => { if (!stopped) setError('Report retrieval is unavailable.'); });
    return () => { stopped = true; };
  }, [job?.id, job?.report_ready, token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(''); setJob(null); setReport(null);
    try {
      const idem = key || crypto.randomUUID();
      setKey(idem);
      const result = await api('', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idem },
        body: JSON.stringify({ project_id: projectId, url }),
      });
      const state = await result.json() as AuditStatus;
      current.current = state.id;
      setJob(state);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Audit request failed.');
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      const result = await api('/' + job.id + '/cancel', { method: 'POST' });
      setJob(await result.json() as AuditStatus);
    } catch { setError('Unable to cancel audit.'); }
  }

  async function exportReport(ext: 'json' | 'csv' | 'html') {
    if (!job) return;
    try {
      const suffix = ext === 'json' ? '/report' : '/report.' + ext;
      const response = await api('/' + job.id + suffix);
      const body = await response.blob();
      const download = document.createElement('a');
      const objectUrl = URL.createObjectURL(body);
      download.href = objectUrl; download.download = 'audit-' + job.id + '.' + ext;
      download.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 500);
    } catch { setError('Unable to download the report.'); }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="surface-card space-y-4">
        <label htmlFor="audit-dev-token" className="form-label">Local development audit token</label>
        <input id="audit-dev-token" className="form-input" type="password"
          autoComplete="off" value={token} required
          onChange={(e) => setToken(e.target.value)} />
        <label htmlFor="audit-project-id" className="form-label">Verified project UUID</label>
        <input id="audit-project-id" className="form-input" required value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          placeholder="00000000-0000-4000-8000-000000000000" />
        <label htmlFor="audit-target-url" className="form-label">Single public page URL</label>
        <input id="audit-target-url" className="form-input" required type="url"
          value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.org/page" />
        <button className="ui-button ui-button-primary" disabled={busy}>
          {busy ? 'Scheduling…' : 'Start private audit'}
        </button>
        <p className="text-xs text-slate-600">
          Development-only. The configured owner must have verified this project. No deep scan,
          automatic edits, or publicly available auditing. Your token is held in this browser
          session's component state, not written to storage.
        </p>
      </form>
      {error && <div role="alert" className="status-notice status-error">{error}</div>}
      {job && (
        <section className="surface-card space-y-4" aria-label="Audit progress">
          <h2 className="text-xl font-bold">Audit status: {job.status.replaceAll('_', ' ')}</h2>
          <p role="status" aria-live="polite">
            Step: {job.progress_step.replaceAll('_', ' ')} · Attempt {job.attempts}
          </p>
          <label htmlFor="audit-progress">Progress: {job.progress_percent}%</label>
          <progress id="audit-progress" value={job.progress_percent} max={100}
            className="block w-full" />
          <p className="break-all text-xs text-slate-600">Job identifier: {job.id}</p>
          {!FINISHED.includes(job.status) && (
            <button type="button" className="ui-button ui-button-outline"
              onClick={cancel} disabled={job.cancel_requested}>
              {job.cancel_requested ? 'Cancellation requested' : 'Cancel audit'}
            </button>
          )}
          {job.error_code && <p className="text-sm text-slate-700">
            Safe status detail: {job.error_code}
          </p>}
        </section>
      )}
      {report && (
        <section className="space-y-4" aria-label="Evidence-backed audit report">
          <div className="surface-card space-y-3">
            <h2 className="text-xl font-bold">Audit report — {report.status}</h2>
            <p className="text-sm text-slate-700">{report.scope}</p>
            <p className="text-sm text-slate-700">{report.uncertainty}</p>
            <div className="flex flex-wrap gap-3">
              {(['json', 'csv', 'html'] as const).map((format) => (
                <button key={format} type="button"
                  className="ui-button ui-button-outline ui-button-small"
                  onClick={() => exportReport(format)}>
                  Download {format.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <h3 className="text-lg font-bold">Observed technical findings</h3>
          {report.findings.length === 0 && <p>No observed findings for this page.</p>}
          {report.findings.map((finding) => (
            <article key={finding.finding_id} className="surface-card space-y-2">
              <h4 className="font-bold">{finding.summary}</h4>
              <p className="text-sm">Severity: {finding.severity}</p>
              <p className="break-all text-sm">Page: {finding.affected_url}</p>
              <p className="text-sm">Evidence: {finding.evidence_quote} ({finding.evidence_ref})</p>
              <p className="text-sm">Suggested correction: {finding.correction}</p>
            </article>
          ))}
          <h3 className="text-lg font-bold">AI interpretations — human review required</h3>
          {report.recommendations.length === 0 && <p>No grounded AI recommendations available.</p>}
          {report.recommendations.map((advice) => (
            <article key={advice.finding_id} className="surface-card space-y-2">
              <p>{advice.advice}</p>
              <p className="text-sm">Evidence quote: {advice.supporting_quote}</p>
              <p className="text-xs">AI interpretation. Not a deterministic SEO finding.</p>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
