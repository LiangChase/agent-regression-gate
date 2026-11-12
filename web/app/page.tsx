"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowDownToLine, BadgeCheck, BarChart3, BookOpenCheck, CircleHelp, Clock3, GitCompareArrows, LayoutDashboard, ListChecks, LoaderCircle, Play, RefreshCw, Search, Server, Settings2, ShieldCheck, X } from "lucide-react";
import { api, Baseline, Case, Dashboard, date, Run, statusLabel } from "../lib/api";
import ComparePage from "./ComparePage";

type Section = "overview" | "runs" | "cases" | "baselines" | "compare" | "settings";
type Settings = { sut: { base_url: string; health_path: string; request_timeout_seconds: number; start_mode: string; revision?: string }; model_metadata: { provider_hint: string; execution_mode_hint: string; credential_configured: boolean; credential_variable: string; notice: string }; storage: { sqlite_path: string; reports_dir: string; cases_path: string } };
const nav: { id: Section; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "总览", icon: LayoutDashboard }, { id: "runs", label: "运行记录", icon: Activity },
  { id: "cases", label: "用例库", icon: ListChecks }, { id: "baselines", label: "基线", icon: BadgeCheck }, { id: "compare", label: "对比", icon: GitCompareArrows }, { id: "settings", label: "SUT 设置", icon: Settings2 },
];

export default function Home() {
  const [section, setSection] = useState<Section>("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sutBaseUrl, setSutBaseUrl] = useState("");
  const [sutRevision, setSutRevision] = useState("");
  const [sutTimeout, setSutTimeout] = useState("60");
  const [executionMode, setExecutionMode] = useState("deterministic");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<any>(null);
  const [trace, setTrace] = useState<any>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [showRun, setShowRun] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [failOn, setFailOn] = useState("critical");
  const [sutCheck, setSutCheck] = useState<any>(null);
  const [baselineName, setBaselineName] = useState("");
  const [baselineReason, setBaselineReason] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [d, r, c, b, s] = await Promise.all([
        api<Dashboard>("/dashboard"), api<{ runs: Run[] }>("/runs?limit=100"), api<{ cases: Case[] }>("/cases"), api<{ baselines: Baseline[] }>("/baselines"), api<Settings>("/settings"),
      ]);
      setDashboard(d); setRuns(r.runs); setCases(c.cases); setBaselines(b.baselines); setSettings(s);
      setSutBaseUrl(s.sut.base_url); setSutRevision(s.sut.revision || ""); setSutTimeout(String(s.sut.request_timeout_seconds)); setExecutionMode(s.model_metadata.execution_mode_hint);
    } catch (e) { setError(e instanceof Error ? e.message : "无法连接本地 Gate API"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!selectedRun) return;
    let active = true;
    const poll = async () => {
      try { const result = await api<any>(`/runs/${encodeURIComponent(selectedRun)}`); if (active) { setRunDetail(result); if (["pass", "fail", "error", "incomplete"].includes(result.run.status)) void refresh(); } }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "读取运行详情失败"); }
    };
    void poll(); const timer = window.setInterval(() => void poll(), 1800);
    return () => { active = false; window.clearInterval(timer); };
  }, [selectedRun, refresh]);

  const filteredCases = useMemo(() => cases.filter(c => `${c.id} ${c.name} ${c.description} ${c.tags.join(" ")}`.toLowerCase().includes(query.toLowerCase())), [cases, query]);
  const filteredRuns = useMemo(() => runs.filter(r => `${r.run_id} ${r.status}`.toLowerCase().includes(query.toLowerCase())), [runs, query]);
  const startRun = async () => {
    setBusy(true); setError("");
    try { const result = await api<{run_id: string}>("/runs", { method: "POST", body: JSON.stringify({ case_ids: picked, fail_on: failOn }) }); setShowRun(false); setPicked([]); setNotice(`评测已加入队列：${result.run_id}`); setSelectedRun(result.run_id); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "启动评测失败"); }
    finally { setBusy(false); }
  };
  const promote = async () => {
    if (!selectedRun || !baselineName.trim() || !baselineReason.trim()) return;
    setBusy(true); setError("");
    try { await api("/baselines", { method: "POST", body: JSON.stringify({ run_id: selectedRun, name: baselineName, reason: baselineReason }) }); setBaselineName(""); setBaselineReason(""); setNotice("基线已保存，历史基线不会被覆盖。"); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "基线保存失败"); }
    finally { setBusy(false); }
  };
  const checkSut = async () => { setBusy(true); setError(""); try { setSutCheck(await api("/sut/check", { method: "POST" })); } catch (e) { setError(e instanceof Error ? e.message : "SUT 检查失败"); } finally { setBusy(false); } };
  const saveSettings = async () => { setBusy(true); setError(""); try { await api("/settings", { method: "PUT", body: JSON.stringify({ base_url: sutBaseUrl, revision: sutRevision, request_timeout_seconds: Number(sutTimeout), execution_mode: executionMode }) }); setNotice("SUT 设置已保存在本地 SQLite，后续评测会使用新配置。"); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "设置保存失败"); } finally { setBusy(false); } };

  return <main className="shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark"><ShieldCheck size={21}/></div><div><b>Agent Gate</b><small>行为回归评测</small></div></div>
      <div className="workspace"><span className="live-dot"/>本地工作区 <span className="local-pill">LOCAL</span></div>
      <nav>{nav.map(item => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => { setSection(item.id); setError(""); }}><item.icon size={18}/>{item.label}{item.id === "runs" && dashboard?.active_runs ? <span className="nav-count">{dashboard.active_runs}</span> : null}</button>)}</nav>
      <div className="sidebar-bottom"><div className="side-note"><CircleHelp size={16}/><span>所有数据保存在本机<br/><small>凭据只由服务端环境读取</small></span></div><div className="version">AGENT REGRESSION GATE <span>v0.1</span></div></div>
    </aside>
    <section className="main-area"><header className="topbar"><div className="crumb">工作区 <span>/</span> <b>{nav.find(n => n.id === section)?.label}</b></div><div className="top-actions"><div className="api-state"><span className="live-dot"/>API 已连接</div><button className="icon-button" onClick={() => void refresh()} title="刷新"><RefreshCw size={17}/></button><button className="primary" onClick={() => setShowRun(true)}><Play size={15} fill="currentColor"/> 新建评测</button></div></header>
      <div className="content">
        {error && <div className="alert error"><AlertTriangle size={17}/>{error}<button onClick={() => setError("")}><X size={15}/></button></div>}
        {notice && <div className="alert success"><BadgeCheck size={17}/>{notice}<button onClick={() => setNotice("")}><X size={15}/></button></div>}
        {loading ? <div className="loading"><LoaderCircle className="spin"/> 正在读取本地项目数据…</div> : <>
          {section === "overview" && <>
            <div className="page-heading"><div><div className="eyebrow">QUALITY CONTROL CENTER</div><h1>评测总览</h1><p>持续验证 Agent 行为规则，让每次变更都有据可查。</p></div><button className="button secondary" onClick={() => void refresh()}><RefreshCw size={15}/> 刷新数据</button></div>
            <div className="stats-grid"><Stat icon={Activity} title="总运行次数" value={dashboard?.run_count ?? 0} hint="最近 50 次" tint="blue"/><Stat icon={BarChart3} title="用例通过率" value={dashboard?.pass_rate == null ? "—" : `${dashboard.pass_rate}%`} hint="按已执行用例统计" tint="green"/><Stat icon={AlertTriangle} title="Critical 失败" value={dashboard?.critical_failures ?? 0} hint="最近 50 次运行" tint="orange"/><Stat icon={Server} title="活动任务" value={dashboard?.active_runs ?? 0} hint={dashboard?.sut_revision || "SUT revision 未标记"} tint="violet"/></div>
            <div className="section-title"><div><h2>最近运行</h2><p>评测结果与 CLI 使用相同的 Gate 判定</p></div><button className="text-button" onClick={() => setSection("runs")}>查看全部 →</button></div>
            <RunTable runs={dashboard?.recent_runs ?? []} onOpen={id => setSelectedRun(id)}/>
            <div className="lower-grid"><div className="panel"><div className="panel-heading"><div><h3>风险分布</h3><p>当前版本的用例等级</p></div><BookOpenCheck size={18}/></div><div className="risk-bars">{["critical","high","medium","low"].map(level => { const count = cases.filter(c => c.risk_level === level).length; return <div className="risk-row" key={level}><span>{level}</span><div><i style={{width: `${cases.length ? Math.max(4, count / cases.length * 100) : 0}%`}} className={`risk-${level}`}/></div><b>{count}</b></div>; })}</div><div className="panel-foot">共 {cases.length} 条可运行用例</div></div><div className="panel principle"><div className="principle-icon"><ShieldCheck size={20}/></div><h3>行为规则的持续证明</h3><p>固定用例、完整轨迹、确定性断言和人工审核基线共同组成可追溯的回归门禁。</p><div className="principle-tags"><span>Cases</span><span>Traces</span><span>Evaluators</span><span>CI Gate</span></div></div></div>
          </>}
          {section === "runs" && <><div className="page-heading"><div><div className="eyebrow">EXECUTION HISTORY</div><h1>运行记录</h1><p>查看每次执行状态、风险结果与可下载证据。</p></div><button className="primary" onClick={() => setShowRun(true)}><Play size={15} fill="currentColor"/> 新建评测</button></div><SearchBox value={query} onChange={setQuery} placeholder="搜索 Run ID 或状态"/><RunTable runs={filteredRuns} onOpen={id => setSelectedRun(id)}/></>}
          {section === "compare" && <ComparePage runs={runs} baselines={baselines} onOpen={id => setSelectedRun(id)}/>}
          {section === "cases" && <><div className="page-heading"><div><div className="eyebrow">VERSIONED BEHAVIOR SPECS</div><h1>用例库</h1><p>用例来自仓库 YAML；控制台提供浏览与筛选，不直接改写版本控制文件。</p></div><button className="primary" onClick={() => setShowRun(true)}><Play size={15} fill="currentColor"/> 运行用例</button></div><SearchBox value={query} onChange={setQuery} placeholder="搜索 ID、名称、描述或标签"/><div className="case-grid">{filteredCases.map(c => <article className="case-card" key={c.id}><div className="case-card-top"><span className="case-id">{c.id}</span><Risk value={c.risk_level}/></div><h3>{c.name}</h3><p>{c.description || "暂无描述"}</p><div className="tags">{c.tags.map(tag => <span key={tag}>{tag}</span>)}</div><div className="case-meta"><span><ListChecks size={14}/>{c.rules.length} 条断言规则</span><span><Activity size={14}/>{c.turns.length} 轮对话</span></div><button className="text-button" onClick={() => { setPicked([c.id]); setShowRun(true); }}>运行此用例 →</button></article>)}</div>{filteredCases.length === 0 && <Empty title="没有匹配的用例" desc="调整搜索条件，或检查 cases 配置。"/>}</>}
          {section === "baselines" && <><div className="page-heading"><div><div className="eyebrow">REVIEWED EXPECTATIONS</div><h1>基线与对比</h1><p>基线只在人工审核后显式提升，普通运行不会覆盖已有基线。</p></div></div><div className="panel baseline-panel"><div className="section-title compact"><div><h2>已审核基线</h2><p>{baselines.length} 个快照</p></div></div>{baselines.length ? <div className="baseline-list">{baselines.map(b => <div className="baseline-row" key={b.name}><div className="baseline-mark"><BadgeCheck size={18}/></div><div className="baseline-info"><b>{b.name}</b><span>{b.reason}</span><small>Run {b.run_id} · {date(b.saved_at)}</small></div><button className="button secondary small" onClick={() => setSection("compare")}>去对比</button></div>)}</div> : <Empty title="尚未创建基线" desc="在成功或已审核的运行详情中填写名称和理由后显式提升。"/>}</div><div className="panel compare-panel"><h3>运行对比</h3><p>在对比页面中，每条运行可独立选择基线并查看新增失败、已修复与持续失败。</p><button className="button secondary" onClick={() => setSection("compare")}><GitCompareArrows size={15}/> 打开对比页面</button></div></>}
          {section === "settings" && <><div className="page-heading"><div><div className="eyebrow">LOCAL CONFIGURATION</div><h1>SUT 设置</h1><p>修改仅保存在本机 SQLite，不覆盖仓库配置文件。</p></div><button className="button secondary" onClick={() => void checkSut()} disabled={busy}><RefreshCw size={15}/> 检查连接</button></div><div className="settings-grid"><div className="panel"><div className="panel-heading"><div><h3>被测系统</h3><p>新的配置立即用于后续 Gate 运行</p></div><Server size={18}/></div><label className="form-setting">基础地址<input value={sutBaseUrl} onChange={e => setSutBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8000"/></label><label className="form-setting">SUT Revision<input value={sutRevision} onChange={e => setSutRevision(e.target.value)} placeholder="可选，例如 commit SHA"/></label><label className="form-setting">请求超时（秒）<input type="number" min="1" max="600" value={sutTimeout} onChange={e => setSutTimeout(e.target.value)}/></label><label className="form-setting">运行模式<select value={executionMode} onChange={e => setExecutionMode(e.target.value)}><option value="deterministic">deterministic（不代表模型输出确定）</option><option value="live">live</option></select></label><div className="settings-actions"><button className="primary" disabled={busy || !sutBaseUrl.trim()} onClick={() => void saveSettings()}>{busy ? <LoaderCircle className="spin" size={15}/> : <BadgeCheck size={15}/>} 保存设置</button></div>{sutCheck && <div className={`check-result ${sutCheck.healthy ? "ok" : "bad"}`}>{sutCheck.healthy ? "连接正常" : "连接失败"} · {sutCheck.status_code ?? sutCheck.error} · {sutCheck.latency_ms ? `${sutCheck.latency_ms} ms` : ""}</div>}</div><div className="panel"><div className="panel-heading"><div><h3>模型配置提示</h3><p>外部托管的 SUT 可使用独立模型配置</p></div><Settings2 size={18}/></div><Setting label="Provider 提示" value={settings?.model_metadata.provider_hint}/><Setting label="服务端凭据" value={`${settings?.model_metadata.credential_configured ? "已配置" : "未配置"} (${settings?.model_metadata.credential_variable || "—"})`}/><div className="security-note"><ShieldCheck size={17}/><span>密钥不会回传明文，也不会存入浏览器存储。{settings?.model_metadata.notice}</span></div></div><div className="panel storage-panel"><h3>本地存储</h3><Setting label="SQLite 元数据" value={settings?.storage.sqlite_path}/><Setting label="报告与轨迹" value={settings?.storage.reports_dir}/><Setting label="用例来源" value={settings?.storage.cases_path}/></div></div></>}
        </>}
      </div>
    </section>
    {showRun && <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setShowRun(false); }}><section className="modal"><div className="modal-heading"><div><div className="eyebrow">NEW EVALUATION</div><h2>启动评测</h2><p>任务在服务端后台执行，可在运行详情中查看进度。</p></div><button className="icon-button" onClick={() => setShowRun(false)}><X size={18}/></button></div><label className="field-label">选择用例 <span>未选择时运行全部 {cases.length} 条</span></label><div className="picker-list">{cases.map(c => <label className="picker-item" key={c.id}><input type="checkbox" checked={picked.includes(c.id)} onChange={e => setPicked(prev => e.target.checked ? [...prev, c.id] : prev.filter(id => id !== c.id))}/><span><b>{c.id}</b> {c.name}</span><Risk value={c.risk_level}/></label>)}</div><label className="field-label" htmlFor="failOn">失败阈值</label><select id="failOn" value={failOn} onChange={e => setFailOn(e.target.value)}><option value="critical">Critical</option><option value="high">High 及以上</option><option value="medium">Medium 及以上</option><option value="low">Low 及以上</option><option value="any">任意失败</option></select><div className="modal-foot"><span><ShieldCheck size={15}/> 相同 Gate 规则用于 CLI / CI</span><button className="primary" disabled={busy || !cases.length} onClick={() => void startRun()}>{busy ? <LoaderCircle className="spin" size={15}/> : <Play size={14} fill="currentColor"/>} 开始运行</button></div></section></div>}
    {selectedRun && <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) { setSelectedRun(null); setTrace(null); } }}><section className="detail-drawer"><div className="drawer-heading"><div><div className="eyebrow">RUN EVIDENCE</div><h2>运行详情</h2><code>{selectedRun}</code></div><button className="icon-button" onClick={() => { setSelectedRun(null); setTrace(null); }}><X size={18}/></button></div>{!runDetail ? <div className="loading"><LoaderCircle className="spin"/> 正在加载运行详情…</div> : <><div className="drawer-status"><Status value={runDetail.run.status}/><span>创建于 {date(runDetail.run.created_at)}</span>{runDetail.run.completed_at && <span>结束于 {date(runDetail.run.completed_at)}</span>}</div>{runDetail.report ? <><div className="detail-kpis"><div><small>通过用例</small><b>{runDetail.report.summary?.passed ?? 0}/{runDetail.report.summary?.case_count ?? 0}</b></div><div><small>Critical 失败</small><b>{runDetail.report.gate?.critical_failures ?? 0}</b></div><div><small>阻断断言</small><b>{runDetail.report.gate?.blocking_assertions ?? 0}</b></div></div><div className="drawer-actions"><a className="button secondary small" href={`/api/runs/${encodeURIComponent(selectedRun)}/report/json`}><ArrowDownToLine size={14}/> JSON</a><a className="button secondary small" href={`/api/runs/${encodeURIComponent(selectedRun)}/report/md`}><ArrowDownToLine size={14}/> Markdown</a></div><h3 className="drawer-section-title">用例结果</h3><div className="result-list">{runDetail.report.cases?.map((c: any) => <article className="result-card" key={c.case_id}><div className="result-head"><div><b>{c.case_id}</b><span>{c.name}</span></div><Status value={c.status}/></div>{c.error_message && <p className="error-copy">{c.error_category}: {c.error_message}</p>}<div className="assertions">{c.assertions?.map((a: any) => <div key={a.assertion_id} className={`assertion ${a.passed ? "assert-pass" : "assert-fail"}`}><i/>{a.assertion_id} · {a.severity}<span>{a.message}</span></div>)}</div>{c.trace_path ? <button className="text-button" onClick={async () => { try { setTrace(await api(`/runs/${encodeURIComponent(selectedRun)}/traces/${encodeURIComponent(c.case_id)}`)); } catch (e) { setError(e instanceof Error ? e.message : "无法读取 Trace"); } }}>查看完整 Trace →</button> : <small className="muted">无可用 Trace{c.status === "incomplete" ? " · 本次采集不完整" : ""}</small>}</article>)}</div><label className="field-label baseline-form-title">审核后提升为基线</label><div className="baseline-form"><input placeholder="基线名称，如 release-2026-11" value={baselineName} onChange={e => setBaselineName(e.target.value)}/><input placeholder="审核理由（必填）" value={baselineReason} onChange={e => setBaselineReason(e.target.value)}/><button className="button secondary" disabled={busy || !baselineName.trim() || !baselineReason.trim()} onClick={() => void promote()}><BadgeCheck size={14}/> 提升基线</button></div></> : <div className="loading"><LoaderCircle className="spin"/> 评测运行中，自动刷新状态…</div>}</>}{trace && <div className="trace-modal"><div className="trace-head"><b>Trace · {trace.case_id}</b><button className="icon-button" onClick={() => setTrace(null)}><X size={16}/></button></div><pre>{JSON.stringify(trace, null, 2)}</pre></div>}</section></div>}
  </main>;
}

function Stat({ icon: Icon, title, value, hint, tint }: { icon: typeof Activity; title: string; value: string | number; hint: string; tint: string }) { return <div className="stat-card"><div className={`stat-icon ${tint}`}><Icon size={18}/></div><div className="stat-title">{title}</div><div className="stat-value">{value}</div><div className="stat-hint">{hint}</div></div>; }
function Risk({ value }: { value: string }) { return <span className={`risk-badge ${value}`}>{value}</span>; }
function Status({ value }: { value: string }) { return <span className={`status-badge ${value}`}><i/>{statusLabel[value] || value}</span>; }
function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) { return <div className="search-wrap"><Search size={17}/><input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}/></div>; }
function Setting({ label, value }: { label: string; value?: string | number }) { return <div className="setting-row"><span>{label}</span><code>{value || "—"}</code></div>; }
function Empty({ title, desc }: { title: string; desc: string }) { return <div className="empty"><div><Clock3 size={20}/></div><b>{title}</b><p>{desc}</p></div>; }
function RunTable({ runs, onOpen }: { runs: Run[]; onOpen: (id: string) => void }) {
  if (!runs.length) return <div className="panel"><Empty title="还没有运行记录" desc="启动一次评测后，运行状态和报告会显示在这里。"/></div>;
  return <div className="table-wrap"><table><thead><tr><th>运行</th><th>状态</th><th>用例</th><th>通过率</th><th>开始时间</th><th/></tr></thead><tbody>{runs.map(run => { const summary = run.summary || {}; const rate = summary.case_count ? `${Math.round((summary.passed || 0) / summary.case_count * 100)}%` : "—"; return <tr key={run.run_id}><td><button className="run-link" onClick={() => onOpen(run.run_id)}><b>{run.run_id.slice(0, 12)}</b><small>fail on {run.fail_on}</small></button></td><td><Status value={run.status}/></td><td>{summary.case_count || run.case_count}</td><td><span className={rate === "100%" ? "green-text" : ""}>{rate}</span></td><td>{date(run.started_at || run.created_at)}</td><td><button className="text-button" onClick={() => onOpen(run.run_id)}>详情 →</button></td></tr>; })}</tbody></table></div>;
}
