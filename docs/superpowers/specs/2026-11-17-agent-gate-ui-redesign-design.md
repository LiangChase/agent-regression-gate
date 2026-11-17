# Agent Regression Gate Web Console — Dark Technical Console Redesign

- Date: 2026-11-17
- Status: proposed
- Scope: `web/` only; no API, runner, evaluator, or data-contract changes

## 1. Intent

The console already contains the right product capabilities: runs, cases, traces, baselines, comparison, and SUT settings. Its current visual language is a generic light admin dashboard. The redesign should make it read as a **developer quality console**: dense, precise, evidence-first, and visibly connected to the Gate's behavior-regression purpose.

The primary users are the project owner and reviewers inspecting a local single-user tool. They need to answer three questions quickly:

1. Is the current SUT behavior healthy?
2. Which run, case, or assertion needs attention?
3. Can I inspect the evidence and compare it with a reviewed baseline?

## 2. Goals

- Establish a distinctive dark technical identity without changing functionality.
- Improve scanning of run status, risk level, pass rate, and failures.
- Make evidence (trace, report, baseline diff) feel first-class and easy to reach.
- Improve keyboard focus, contrast, touch targets, responsive layout, and reduced-motion behavior.
- Keep the existing Next.js app and `lucide-react` icons; do not add a UI framework or chart dependency.

## 3. Non-goals

- No backend/API/routing changes.
- No new authentication, multi-user, or deployment work.
- No new data visualisation library.
- No light/dark theme toggle in this pass; dark is the selected direction.
- No rewrite of the run/compare state machines.
- No change to Gate decisions, case data, or reports.

## 4. Approaches Considered

| Approach | Trade-off | Decision |
|---|---|---|
| A. Dark technical console | Strongest identity; matches developer-tool/IDE guidance; needs careful contrast work | **Selected** |
| B. Refined light data-dense dashboard | Safest and most familiar; less visibly a redesign | Rejected for this pass |
| C. Dual-theme console | Best long-term flexibility; roughly doubles visual QA and CSS state work | Deferred |

The ui-ux-pro-max design library returned:

- Developer Tool / IDE → Dark Mode (OLED) + Minimalism & Swiss Style, Real-Time Monitor + Terminal, dark syntax colors with blue focus.
- Data-Dense Dashboard → 12-column grid, compact KPI cards, dense tables, blue/amber data colors, Fira/JetBrains-style technical typography.
- Accessibility baseline → 4.5:1 contrast, visible focus, 44px targets, reduced-motion support, responsive at 375/768/1024/1440.

The landing-page “pattern” result was not used; this is an application console, not a marketing page. The selected system combines the Developer Tool mood with Data-Dense Dashboard structure.

## 5. Design System

### 5.1 Color tokens

```css
--bg: #0B1220;
--bg-elevated: #101827;
--surface: #111C2E;
--surface-2: #16233A;
--surface-3: #1B2A44;
--border: #24334D;
--border-strong: #334766;
--text: #E6EDF7;
--text-muted: #96A7BE;
--text-faint: #7C8FA8;
--primary: #4F8CFF;
--primary-strong: #2563EB;
--primary-soft: rgba(79, 140, 255, 0.12);
--on-primary: #FFFFFF;
--success: #22C55E;
--success-soft: rgba(34, 197, 94, 0.12);
--warning: #F59E0B;
--warning-soft: rgba(245, 158, 11, 0.12);
--danger: #EF4444;
--danger-soft: rgba(239, 68, 68, 0.12);
--info: #38BDF8;
--violet: #A78BFA;
--focus: #60A5FA;
--shadow: 0 24px 70px rgba(0, 0, 0, 0.38);
```

Semantic mapping:

- pass / healthy: green
- fail / error: red
- incomplete / warning: amber
- running / queued: blue
- active tasks / secondary metric: violet
- primary actions and focus: blue

Do not use color alone: every status and risk badge keeps a text label and a dot or icon.

Contrast decisions:

- Solid primary buttons use `--primary-strong` (`#2563EB`) with white text: 5.17:1. `--primary` is reserved for focus rings, borders, soft tints, and non-text accents where 3:1 is sufficient.
- `--text-faint` is `#7C8FA8`: 5.17:1 on `--surface` and 4.76:1 on `--surface-2`. Do not use it on `--surface-3` without rechecking.
- Muted text `--text-muted` is 6.97:1 on `--surface`; status colors are checked against `--bg` and their soft backgrounds.

### 5.2 Typography

- Body: `IBM Plex Sans`, `Noto Sans SC`, `Microsoft YaHei`, sans-serif; base 14px, line-height 1.55.
- Technical labels, IDs, KPI numbers, table headers, trace: `JetBrains Mono`, `SFMono-Regular`, `Consolas`, monospace.
- Chinese headings use the body family for legibility; English eyebrows and IDs use mono.
- Load Google Fonts with `display=swap` through a CSS `@import`; if offline, the declared fallback stack is used. No build-time font fetch.

### 5.3 Shape and spacing

- App background uses a subtle radial blue/green glow, not heavy gradients.
- Panels: 14px radius, 1px border, `--surface`, compact 16-20px padding.
- Interactive controls: minimum 44px height/hit area (buttons, icon buttons, inputs, selects). Table text actions get a 44px hit area even when the visible label is compact.
- Focus ring: 2px `--focus` with 2px offset.
- Table row height: 56px; sticky header; hover tint `--primary-soft`.
- KPI cards: 4-column grid, mono value, compact label, small status hint; optional top accent line.
- Use an 8px base spacing scale: 8, 12, 16, 20, 24, 32, 40.

## 6. Page Design

### 6.1 Shell

```text
┌ rail 240 ┬ topbar 64 ──────────────────────────────────────┐
│ brand    │ 工作区 / 总览          API ●  刷新   + 新建评测 │
│ workspace│                                                │
│ nav      │  page heading                                  │
│          │  KPI row                                       │
│          │  main grid: table 8 cols / side panel 4 cols  │
│ bottom   │                                                │
└──────────┴────────────────────────────────────────────────┘
```

- Sidebar: brand mark, local workspace chip, nav with active left accent, active-run count, bottom local-data note and version.
- Topbar: breadcrumb, API state dot, refresh icon button, primary “新建评测” button.
- API state dot reflects the last Gate API request: “API 已连接” after a successful load, “连接异常” after a failed request. It is not a separate health poll and does not claim SUT health; the Settings page owns the explicit SUT check.
- Content max-width 1440px, 32px horizontal padding on desktop.

### 6.2 Overview

- Four KPI cards: total runs, pass rate, critical failures, active tasks. Add SUT revision as a small mono hint.
- Recent runs table occupying 8/12 columns; risk distribution and “behavior rules are continuously proven” panel occupying 4/12.
- Failure-oriented empty state: if there are no runs, show the first-run CTA, not a blank table.
- Pass rate uses a compact bar or ring-like meter; critical failures use red only when non-zero.

### 6.3 Runs

- Toolbar: search (Run ID/status), archived toggle, new run. Preserve the existing client-side search.
- Dense table: Run ID (mono), status, cases, pass rate, `fail on` threshold hint, started time, actions.
- Sticky header, zebra-free but hover-highlighted rows, row action area right-aligned.
- On narrow screens: horizontal scroll wrapper with a visible hint; do not collapse columns in a way that hides status.
- Run detail remains a right-side drawer: status header, KPI strip, JSON/Markdown downloads, case result cards, assertion rows, trace action, baseline form.
- Add Escape-to-close and initial focus to drawer/modal; use `role="dialog"` and `aria-modal="true"`.

### 6.4 Cases

- Search plus risk filter chips (all/critical/high/medium/low), client-side only.
- Card grid: 3 columns desktop, 2 tablet, 1 phone; risk stripe on the left edge; mono case ID; tags; rule/turn counts; “运行此用例”.
- Card hover lifts slightly and highlights the border; focus-visible matches.

### 6.5 Baselines

- Reviewed baseline list with name, reason, source run, saved date, compare/delete actions.
- The “compare” action navigates to the Compare page; it does not preselect a baseline or lift comparison state in this pass.
- Empty state explains the explicit-review workflow.
- Delete confirmation stays a native confirm for now; no new modal state machine.

### 6.6 Compare

- Keep per-row baseline selection and independent result state.
- Result summary chips: new failures (red), fixed (green), persistent (amber), changed (blue), missing evidence (violet), added/removed cases (muted).
- Diff item lists use mono code chips; downloads and Markdown preview stay reachable.
- Incomparable runs get a prominent warning block, not just a small label.

### 6.7 Settings

- Two-column layout: SUT connection and model hints; storage full-width.
- Inputs have visible labels, helper text, and inline validation.
- “检查连接” shows a clear healthy/unhealthy result with latency.
- Credential state is text-only; never display a secret.
- Save state shows a success/error toast and the persisted scope.

### 6.8 New evaluation modal

- Case picker with search and risk chips, selected count, “全选/清空” actions.
- Retain the existing **失败阈值 (`fail_on`)** select with the same options: critical, high, medium, low, any.
- Keep the existing case IDs and API payload.
- Primary action shows the selected count and disabled state when no cases exist.
- When no cases are selected, the server still means “all cases”; label that explicitly.

### 6.9 Trace viewer

- Full-screen terminal-style panel: dark background, mono text, sticky header with case ID and close/copy actions.
- Keep the JSON view; add a copy button and a scrollable, focusable region.
- Use a distinct border and no surrounding page interaction.

## 7. Components

Presentational components to extract or restyle:

- `AppShell`, `Sidebar`, `Topbar`
- `PageHeader`
- `KpiCard`
- `Panel`
- `StatusBadge`, `RiskBadge`
- `RunTable`
- `CaseCard`
- `BaselineRow`
- `CompareRow` (existing `ComparePage` remains the owner of comparison state)
- `Modal`, `Drawer`
- `TraceViewer`
- `Toast`
- `Field`, `EmptyState`, `Skeleton`

The first pass may keep most components local to `page.tsx` and `ComparePage.tsx`; extraction is allowed where it reduces duplication. No new state library.

## 8. Responsive Behavior

- `>=1280px`: 240px rail, 4 KPI columns, 3 case columns.
- `1024–1279px`: 220px rail, 2x2 KPI grid, 2 case columns.
- `<=900px`: 64px icon rail; labels visually hidden but available via `aria-label`/tooltip; 2 KPI columns; 2 case columns.
- `<=560px`: single column; topbar compacts; primary action becomes icon+short label; modals/drawer near-full-screen; tables scroll horizontally; toast full-width.
- No horizontal page scroll at 375px; only the table wrapper may scroll.

## 9. Accessibility and Motion

- All interactive controls have visible `:focus-visible` rings.
- Icon-only buttons have `aria-label`.
- Nav uses `aria-current="page"` for the active section.
- Modals/drawers use `role="dialog"`, `aria-modal="true"`, Escape to close, and initial focus.
- Toasts use `role="status"`/`aria-live="polite"`; errors use assertive or a persistent alert.
- Status/risk labels include text, not color alone.
- Table headers use `scope="col"`; numeric metrics are right-aligned where useful.
- Motion: 150–220ms ease-out for hover/focus and 8px fade/slide for section changes. No scroll-triggered animation. Disable non-essential motion under `prefers-reduced-motion: reduce`.
- No emojis as icons; keep `lucide-react` SVGs.

## 10. Implementation Boundaries

- Files expected to change:
  - `web/app/globals.css` (primary rewrite)
  - `web/app/page.tsx` (markup, aria, small interaction improvements)
  - `web/app/ComparePage.tsx` (semantic classes, aria, compact diff presentation)
  - `web/app/layout.tsx` (font/theme metadata if needed)
  - optional `web/app/components/*` for extracted presentational pieces
- No changes to `web/lib/api.ts` endpoint shapes.
- No dependency additions beyond the existing `lucide-react`.
- No changes to Python, cases, workflows, or rulesets.

## 11. Verification

1. `npm run typecheck`
2. `npm run build`
3. Start the API and web console; visually inspect:
   - 1440x900 overview, runs, cases, baselines, compare, settings
   - 1024x768 and 768x1024
   - 375x812
4. Keyboard-only pass: sidebar navigation, new evaluation modal, run drawer, trace viewer, compare controls, settings form.
5. Verify all existing actions still work: start run, archive/unarchive, save baseline, delete baseline, compare, download JSON/Markdown, preview Markdown, save settings, check SUT.
6. Verify contrast for text, muted text, status badges, and primary buttons.
7. Confirm no API/data-contract diff and no horizontal page scroll at 375px.

## 12. Design Calls Left to the Builder

- Use CSS `@import` for fonts with a system fallback; avoid a build-time network dependency.
- Keep the dark direction only; add a theme toggle later only if requested.
- Use CSS transitions instead of adding GSAP.
- Keep the existing case/diff state logic; extract components only where it improves clarity.
- Keep the native `window.confirm` for baseline deletion in this pass.

## 13. Builder-Check Resolutions

The independent builder review raised five questions; all are resolved here without expanding scope:

1. **API state dot:** reflects the last Gate API request, not a new health poll; the Settings page keeps the explicit SUT check.
2. **Fail-on threshold:** retained in the new-evaluation modal; run rows keep a compact `fail on` hint.
3. **Target size:** 44px minimum for interactive controls; compact text actions get a 44px hit area.
4. **Contrast:** solid primary buttons use `--primary-strong`; `--text-faint` is raised to `#7C8FA8`; token usage is mapped accordingly.
5. **Baselines compare:** stays a navigation action; comparison state remains owned by `ComparePage`.

