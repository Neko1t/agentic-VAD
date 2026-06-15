# REPL Console Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the REPL console into a modern research-console-style terminal with a stronger header, clearer overview cards, tighter action recommendations, and a more polished visual rhythm while keeping the same keyboard-first workflow.

**Architecture:** Keep the command model and execution path unchanged. Refactor only the REPL rendering layer first, then apply small shell prompt improvements if needed. Reuse the existing status and results snapshots so the new visuals are purely presentational.

**Tech Stack:** Python, Rich, pytest

---

## File Structure

- Modify: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
  - add modern console header, overview cards, action queue, and compact result blocks
- Modify: `E:\ClaudeProject\VAD\src\app\repl_shell.py`
  - improve prompt styling and screen composition
- Modify: `E:\ClaudeProject\VAD\src\app\status.py`
  - expose any small helper data needed for visual grouping
- Test: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`
  - verify the modern render includes the new section titles and key data
- Test: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`
  - verify the startup screen and prompt still work after the refactor
- Modify: `E:\ClaudeProject\VAD\docs\scripts_guide.md`
  - only if the prompt or default screen wording changes materially

## Task 1: Modernize the startup overview render

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`

- [ ] **Step 1: Write the failing startup-render test**

Add a test that asserts the overview render contains:
- `Agentic VAD Console`
- `Next Actions`
- `Environment`
- `Models`
- `Datasets`
- `Outputs`

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: FAIL because the modern header/cards have not been added yet.

- [ ] **Step 3: Write the minimal rendering upgrade**

Implement a modern startup render with:
- compact header strip
- overview cards / grouped panels
- explicit next-actions block
- compact prompt hint

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_renderer.py tests/test_repl_renderer.py
git commit -m "feat: modernize repl startup overview"
```

## Task 2: Add a compact prompt style

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\repl_shell.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`

- [ ] **Step 1: Write the failing prompt test**

Add a test asserting the shell prompt text includes readiness hints such as:
- `mini:ready`
- `full:missing`

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: FAIL because the prompt is still generic.

- [ ] **Step 3: Implement the minimal prompt formatting**

Add a small helper that formats prompt text from the current overview state.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_shell.py tests/test_repl_shell.py
git commit -m "feat: add contextual repl prompt"
```

## Task 3: Modernize doctor and result summaries

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`

- [ ] **Step 1: Write failing tests for doctor and compare styling**

Add assertions that doctor rendering includes grouped headings such as:
- `Runtime`
- `Dataset Inputs`
- `Outputs`

Add assertions that compare rendering includes:
- `Compare Summary`
- `ROC AUC`
- `PR AUC`

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: FAIL because the grouped renderers do not exist yet.

- [ ] **Step 3: Implement the minimal grouped renderers**

Refactor doctor/result rendering into clearer sections without changing the
underlying data source.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_renderer.py tests/test_repl_renderer.py
git commit -m "feat: refine repl doctor and result views"
```

## Task 4: Improve run-progress presentation

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`

- [ ] **Step 1: Write failing progress layout tests**

Add assertions that run output contains:
- `Run`
- `Active`
- `Stage Progress`
- `Recent Events`

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: FAIL if the new labels or grouping are missing.

- [ ] **Step 3: Implement the compact run layout**

Make the run view feel more like a dedicated execution panel and less like a
plain data dump.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_renderer.py tests/test_repl_shell.py
git commit -m "feat: improve repl run progress presentation"
```

## Task 5: Regression verification

**Files:**
- No code changes required unless regressions appear

- [ ] **Step 1: Run the focused visual and shell tests**

Run:

```bash
pytest tests/test_repl_renderer.py tests/test_repl_shell.py tests/test_unified_app_entry.py -q
```

Expected: PASS

- [ ] **Step 2: Manually inspect the startup screen**

Run:

```bash
python agentic_vad.py
```

Expected: the new startup layout reads as a modern console, not a flat table
dump.

- [ ] **Step 3: Commit any final doc tweaks**

```bash
git add docs/scripts_guide.md agent.md
git commit -m "docs: align repl visual refresh notes"
```
