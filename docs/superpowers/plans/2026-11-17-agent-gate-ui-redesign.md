# Dark Technical Console Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing Next.js console as a dark, data-dense developer quality console without changing any API, data, or Gate behavior.

**Architecture:** Keep the current client-side state and API calls in `web/app/page.tsx` and `web/app/ComparePage.tsx`. Replace the visual layer in `web/app/globals.css`, add semantic classes and accessibility attributes in the existing JSX, and keep all existing actions working. No new runtime dependencies.

**Tech Stack:** Next.js 16, React 19, TypeScript, `lucide-react`, plain CSS.

**Spec:** [`docs/superpowers/specs/2026-11-17-agent-gate-ui-redesign-design.md`](../specs/2026-11-17-agent-gate-ui-redesign-design.md)

## Global Constraints

- Dark-only in this pass; no theme toggle.
- No API, runner, evaluator, case, workflow, or ruleset changes.
- No new npm dependencies.
- 44px minimum interactive target size; visible `:focus-visible` rings.
- Body text and controls at or above 4.5:1 contrast. Solid primary buttons use `--primary-strong` with white text.
- Keep all existing actions: start run, archive/unarchive, save baseline, delete baseline, compare, JSON/Markdown download, Markdown preview, settings save, SUT check.
- Keep the `fail_on` threshold control in the new-evaluation modal.
- Keep the API state dot as “last Gate API request” state, not a new health poll.
- Respect `prefers-reduced-motion`; no scroll-triggered animation.
- Commit/push only when the user asks.

## Review Focus

- **False API health:** the topbar must not show “connected” after a failed request; test by stopping the API and loading the page.
- **Lost `fail_on`:** the new-evaluation modal must still send the selected threshold; test critical/high/any paths.
- **Small targets:** row actions and icon buttons must retain a 44px hit area; test at 1024px and 375px.
- **Low contrast:** muted text and primary buttons must meet 4.5:1; verify tokens and rendered states.
- **Broken compare action:** the baseline page’s “去对比” must still navigate; the Compare page must keep per-row baseline selection.

## File Map

- `web/app/globals.css` — full visual rewrite: tokens, fonts, shell, typography, tables, cards, forms, modals, responsive, focus, motion.
- `web/app/page.tsx` — semantic classes, aria labels, `aria-current`, dialog semantics, API state label, case-picker search/risk filters, fail-on retention, Escape-to-close.
- `web/app/ComparePage.tsx` — semantic classes, aria labels, diff chips, warning block, keyboard/focus.
- `web/app/layout.tsx` — `theme-color`, description, font preconnect if using CSS import.
- No new component directory in this pass; extract only if `page.tsx` becomes hard to edit.

---

### Task 1: Global tokens, shell, and primitives

**Files:**
- Modify: `web/app/globals.css`
- Modify: `web/app/layout.tsx`

- [ ] Write the token block from the spec (`--bg`, surfaces, borders, text, primary, semantic colors, focus, shadow), font stacks, reset, body background glow, scrollbar, selection, and `:focus-visible`.
- [ ] Style the shell: sidebar 240px, topbar 64px, brand, workspace chip, nav active accent/count, bottom note, main content max-width 1440px.
- [ ] Style primitives: `.primary`, `.button`, `.icon-button`, `.text-button`, `.search-wrap`, `.panel`, `.stat-card`, `.status-badge`, `.risk-badge`, `.tags`, `.alert`, `.loading`, `.empty`.
- [ ] Add responsive shell rules at 1024/900/560px; icon rail at 900px; no page-level horizontal scroll.
- [ ] Run `cd web && npm run typecheck` and `npm run build`.

### Task 2: Overview and information hierarchy

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/globals.css`

- [ ] Add semantic classes for KPI cards, recent-runs panel, risk distribution, and principle panel.
- [ ] Make KPI values mono, labels compact, nonzero critical failures red, active tasks violet, pass rate green.
- [ ] Style the recent-runs table: sticky header, 56px rows, hover tint, mono run IDs, status/risk pills, right-aligned actions.
- [ ] Style risk bars with labels and counts, not color alone.
- [ ] Verify overview at 1440px and 1024px.

### Task 3: Runs, run drawer, and trace viewer

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/globals.css`

- [ ] Style the runs toolbar, archived toggle, table wrapper, row actions, and empty state.
- [ ] Add `scope="col"` to table headers and `aria-label` to icon/search controls.
- [ ] Restyle the run drawer: dialog semantics, sticky header, KPI strip, downloads, case result cards, assertion states, baseline form.
- [ ] Add Escape-to-close for the new-run modal, run drawer, and trace modal; keep click-outside close.
- [ ] Restyle the trace viewer as a dark terminal panel with sticky header and a copy action.
- [ ] Verify archive/unarchive, open detail, trace, JSON/Markdown downloads, and baseline save still work.

### Task 4: Cases page

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/globals.css`

- [ ] Add client-side risk filter chips (all/critical/high/medium/low) next to the search box; filter the existing `filteredCases` list.
- [ ] Style case cards with a risk stripe, mono ID, tags, rule/turn counts, hover/focus states, and 3/2/1 column responsiveness.
- [ ] Keep “运行此用例” behavior unchanged.
- [ ] Verify search + risk filter together and the empty state.

### Task 5: Baselines and Compare

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/ComparePage.tsx`
- Modify: `web/app/globals.css`

- [ ] Restyle baseline rows with name, reason, source run, date, compare/delete actions; keep native confirm deletion.
- [ ] Keep “去对比” as navigation only; do not preselect or lift comparison state.
- [ ] Style comparison rows, baseline select, diff chips, incomparable warning, diff item chips, downloads, Markdown preview, and JSON details.
- [ ] Add `aria-label`s and focus states to compare controls.
- [ ] Verify compare, download JSON/Markdown, Markdown preview, and archived-run visibility.

### Task 6: Settings and new-evaluation modal

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/globals.css`

- [ ] Restyle settings forms with visible labels, helper text, 44px inputs, focus states, connection result, security note, and storage rows.
- [ ] Retain the `fail_on` select and all five options in the new-evaluation modal.
- [ ] Add case-picker search and risk chips; add select-all/clear; keep “no selection means all cases” explicit.
- [ ] Show selected count and disable the primary action only when there are no cases.
- [ ] Verify settings save, SUT check, and starting runs with a subset + each threshold.

### Task 7: Accessibility, motion, and responsive pass

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/ComparePage.tsx`
- Modify: `web/app/globals.css`

- [ ] Add `aria-current="page"` to active nav, `aria-label` to icon-only buttons, `role="dialog"`/`aria-modal` to overlays, and `role="status"`/`aria-live` to toasts.
- [ ] Add `prefers-reduced-motion: reduce` to disable section/hover transitions.
- [ ] Verify keyboard-only navigation: sidebar, new-run modal, run drawer, trace viewer, compare, settings.
- [ ] Verify 1440x900, 1024x768, 768x1024, 375x812; no page-level horizontal scroll.
- [ ] Verify focus rings and contrast for text, muted text, badges, and primary buttons.

### Task 8: Final verification

**Files:**
- All changed `web/` files

- [ ] Run `cd web && npm run typecheck`.
- [ ] Run `cd web && npm run build`.
- [ ] Start `uv run gate --config config/gate.example.yaml serve` and `cd web && npm run dev`; open `http://127.0.0.1:3002`.
- [ ] Exercise every existing action listed in Global Constraints.
- [ ] Confirm the API state changes to “连接异常” when the Gate API is stopped.
- [ ] Confirm `git diff --stat` contains only `web/` files plus the design/plan docs.
- [ ] Do not commit or push until the user asks.

## Self-Review Notes

- Spec coverage: shell, overview, runs/drawer/trace, cases, baselines, compare, settings, new-run modal, responsive, accessibility, motion, and verification each have a task.
- Builder-check resolutions are included: API dot, `fail_on`, 44px targets, contrast tokens, baseline navigation.
- No task changes Python, case data, workflows, or rulesets.
