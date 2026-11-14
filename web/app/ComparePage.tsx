"use client";

import { useState } from "react";
import { ArrowDownToLine, GitCompareArrows, LoaderCircle } from "lucide-react";
import { api, Baseline, date, Run, statusLabel } from "../lib/api";

type DiffItem = { case_id: string; assertion_id: string };
type Incompatibility = { dimension: string; baseline: unknown; current: unknown };
type ComparisonResult = {
  status: string;
  comparable: boolean;
  baseline_run_id?: string;
  current_run_id?: string;
  baseline_sut_revision?: string;
  current_sut_revision?: string;
  incompatibilities?: Incompatibility[];
  new_failures?: DiffItem[];
  fixed?: DiffItem[];
  persistent_failures?: DiffItem[];
  changed_passes?: DiffItem[];
  missing_evidence?: DiffItem[];
  added_cases?: string[];
  removed_cases?: string[];
};
type ComparisonResponse = { comparison_id: string; result: ComparisonResult };

const FINISHED = new Set(["pass", "fail", "error", "incomplete"]);

function DiffList({ title, items }: { title: string; items?: DiffItem[] }) {
  if (!items?.length) return null;
  return <div className="compare-block">
    <h5>{title}（{items.length}）</h5>
    <div className="compare-items">
      {items.map(item => <code key={`${item.case_id}/${item.assertion_id}`}>{item.case_id} / {item.assertion_id}</code>)}
    </div>
  </div>;
}

function CaseList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return <div className="compare-block">
    <h5>{title}（{items.length}）</h5>
    <div className="compare-items">{items.map(id => <code key={id}>{id}</code>)}</div>
  </div>;
}

function CompareRow({ run, baselines, onOpen }: { run: Run; baselines: Baseline[]; onOpen: (id: string) => void }) {
  const [baseline, setBaseline] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<ComparisonResponse | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [mdOpen, setMdOpen] = useState(false);
  const [mdLoading, setMdLoading] = useState(false);
  const [mdError, setMdError] = useState("");

  const finished = FINISHED.has(run.status);
  const result = response?.result;
  const counts = result ? {
    newFailures: result.new_failures?.length ?? 0,
    fixed: result.fixed?.length ?? 0,
    persistent: result.persistent_failures?.length ?? 0,
    changed: result.changed_passes?.length ?? 0,
    missing: result.missing_evidence?.length ?? 0,
    added: result.added_cases?.length ?? 0,
    removed: result.removed_cases?.length ?? 0,
  } : null;

  const compare = async () => {
    if (!baseline) { setError("请先选择基线。"); return; }
    setBusy(true); setError(""); setResponse(null);
    setMarkdown(""); setMdOpen(false); setMdError("");
    try {
      setResponse(await api<ComparisonResponse>("/comparisons", {
        method: "POST",
        body: JSON.stringify({ baseline_name: baseline, current_run_id: run.run_id }),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleMarkdown = async () => {
    if (mdOpen) { setMdOpen(false); return; }
    if (markdown) { setMdOpen(true); return; }
    if (!response) return;
    setMdOpen(true); setMdLoading(true); setMdError("");
    try {
      const result = await fetch(`/api/comparisons/${encodeURIComponent(response.comparison_id)}/report.md`, { cache: "no-store" });
      if (!result.ok) throw new Error(`无法加载对比报告（${result.status}）`);
      setMarkdown(await result.text());
    } catch (e) {
      setMdError(e instanceof Error ? e.message : "无法加载对比报告");
    } finally {
      setMdLoading(false);
    }
  };

  return <div className="panel compare-row">
    <div className="compare-row-head">
      <button className="run-link" onClick={() => onOpen(run.run_id)}>
        <b>{run.run_id.slice(0, 12)}</b>
        <small>{date(run.started_at || run.created_at)} · {run.case_count} 条用例</small>
      </button>
      <span className={`status-badge ${run.status}`}><i/>{statusLabel[run.status] || run.status}</span>
      {run.archived_at ? <span className="archived-pill">已归档</span> : null}
      <div className="compare-row-controls">
        <select value={baseline} onChange={e => setBaseline(e.target.value)} disabled={busy || !finished}>
          <option value="">{finished ? "选择基线" : "运行未完成"}</option>
          {baselines.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        <button className="button secondary small" disabled={!finished || !baseline || busy} onClick={() => void compare()}>
          {busy ? <LoaderCircle className="spin" size={13}/> : <GitCompareArrows size={13}/>} 对比
        </button>
      </div>
    </div>
    {error && <p className="error-copy compare-row-error">{error}</p>}
    {result && counts && <div className="comparison-result compare-row-result">
      <h4>对比结果：{result.status}</h4>
      <div className="diff-chips">
        <span>新增失败 {counts.newFailures}</span>
        <span>已修复 {counts.fixed}</span>
        <span>持续失败 {counts.persistent}</span>
        <span>结果变化 {counts.changed}</span>
        <span>证据缺失 {counts.missing}</span>
        <span>新增用例 {counts.added}</span>
        <span>移除用例 {counts.removed}</span>
      </div>
      {result.incompatibilities?.length ? <div className="compare-block">
        <h5>不可比项（{result.incompatibilities.length}）</h5>
        <div className="compare-items">
          {result.incompatibilities.map(item => <code key={item.dimension}>{item.dimension}</code>)}
        </div>
      </div> : null}
      <DiffList title="新增失败" items={result.new_failures}/>
      <DiffList title="已修复" items={result.fixed}/>
      <DiffList title="持续失败" items={result.persistent_failures}/>
      <DiffList title="证据缺失" items={result.missing_evidence}/>
      <DiffList title="通过的断言结果变化" items={result.changed_passes}/>
      <CaseList title="新增用例" items={result.added_cases}/>
      <CaseList title="移除用例" items={result.removed_cases}/>
      {response ? <>
        <div className="compare-downloads">
          <a href={`/api/comparisons/${encodeURIComponent(response.comparison_id)}/report/json`}><ArrowDownToLine size={12}/> 下载 JSON</a>
          <a href={`/api/comparisons/${encodeURIComponent(response.comparison_id)}/report.md`}><ArrowDownToLine size={12}/> 下载 Markdown</a>
          <button type="button" className="text-button" onClick={() => void toggleMarkdown()}>{mdOpen ? "收起 Markdown" : "预览 Markdown"}</button>
        </div>
        {mdError && <p className="error-copy compare-row-error">{mdError}</p>}
        {mdOpen && <pre className="json-box compare-md">{mdLoading ? "正在加载对比报告…" : markdown}</pre>}
        <details className="compare-json"><summary>查看 JSON</summary><pre className="json-box">{JSON.stringify(result, null, 2)}</pre></details>
      </> : null}
      {(result.baseline_sut_revision || result.current_sut_revision) ? <p className="compare-revisions">
        SUT revision：{result.baseline_sut_revision ?? "—"} → {result.current_sut_revision ?? "—"}
      </p> : null}
    </div>}
  </div>;
}

export default function ComparePage({ runs, baselines, onOpen }: { runs: Run[]; baselines: Baseline[]; onOpen: (id: string) => void }) {
  return <>
    <div className="page-heading">
      <div>
        <div className="eyebrow">BASELINE DIFF</div>
        <h1>运行对比</h1>
        <p>每条运行独立选择基线并生成对比；结果只属于当前行，不会互相影响。</p>
      </div>
    </div>
    {!baselines.length ? <div className="panel"><div className="loading">尚无已审核基线，请先在运行详情中提升基线。</div></div> : null}
    {!runs.length ? <div className="panel"><div className="loading">暂无可对比的运行。</div></div> : null}
    {baselines.length && runs.length ? <div className="compare-list">
      {runs.map(run => <CompareRow key={run.run_id} run={run} baselines={baselines} onOpen={onOpen}/>)}
    </div> : null}
  </>;
}
