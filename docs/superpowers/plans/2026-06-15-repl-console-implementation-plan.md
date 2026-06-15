# REPL Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current default Textual home launch with a persistent Rich-based REPL console that auto-runs doctor, recommends next commands, supports short shell commands, and runs mini/full workflows with live progress and result summaries.

**Architecture:** Add a small REPL layer on top of the existing status/orchestrator/results modules. Keep the Typer CLI for direct automation, but route the no-subcommand entry path into the new REPL session. Reuse `WorkflowMonitor` and persisted result summaries rather than inventing a second execution pipeline.

**Tech Stack:** Python, Typer, Rich, pytest

---

## File Structure

- Create: `E:\ClaudeProject\VAD\src\app\repl_parser.py`
  - parse short interactive commands into typed actions
- Create: `E:\ClaudeProject\VAD\src\app\repl_state.py`
  - define session state container and helper methods
- Create: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
  - render startup summaries, recommendations, run summaries, and errors
- Create: `E:\ClaudeProject\VAD\src\app\repl_commands.py`
  - command handlers calling status/orchestrator/results helpers
- Create: `E:\ClaudeProject\VAD\src\app\repl_shell.py`
  - persistent command loop and run integration
- Modify: `E:\ClaudeProject\VAD\src\app\cli.py`
  - default root callback launches REPL shell instead of Textual home
- Modify: `E:\ClaudeProject\VAD\src\app\status.py`
  - add convenience helpers for run readiness and recommended commands
- Modify: `E:\ClaudeProject\VAD\src\app\orchestrator.py`
  - add thin helpers for default mini/full requests if needed
- Modify: `E:\ClaudeProject\VAD\docs\scripts_guide.md`
  - document the new default interactive shell behavior and command style
- Modify: `E:\ClaudeProject\VAD\agent.md`
  - update current entrypoint behavior and architecture notes
- Create: `E:\ClaudeProject\VAD\tests\test_repl_parser.py`
- Create: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`
- Create: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`
- Modify: `E:\ClaudeProject\VAD\tests\test_unified_app_entry.py`

## Task 1: Add the REPL command parser

**Files:**
- Create: `E:\ClaudeProject\VAD\src\app\repl_parser.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_parser.py`

- [ ] **Step 1: Write the failing parser tests**

Add tests covering:
- `help`
- `doctor`
- `status`
- `download models-core`
- `build mini`
- `run mini`
- `run full`
- `run stage pipeline`
- invalid command

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_parser.py -q
```

Expected: FAIL because `src.app.repl_parser` does not exist yet.

- [ ] **Step 3: Write minimal parser implementation**

Implement:
- typed command dataclass or simple Pydantic-free structure
- token parsing with `shlex.split`
- support aliases `quit` -> `exit`
- clear error objects/messages for unknown commands

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_parser.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_parser.py tests/test_repl_parser.py
git commit -m "feat: add repl command parser"
```

## Task 2: Add session state and recommendation helpers

**Files:**
- Create: `E:\ClaudeProject\VAD\src\app\repl_state.py`
- Modify: `E:\ClaudeProject\VAD\src\app\status.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`

- [ ] **Step 1: Write failing tests for startup recommendations**

Cover:
- incomplete workspace produces missing items
- mini-ready/full-missing workspace recommends `run mini`
- missing assets recommend the external `assets download` command

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: FAIL because recommendation helpers do not exist yet.

- [ ] **Step 3: Implement minimal state and status helpers**

Add:
- REPL session state object
- helper that derives `mini_ready`, `full_ready`, `missing_items`, and
  `recommended_commands`

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_state.py src/app/status.py tests/test_repl_renderer.py
git commit -m "feat: add repl session state and recommendations"
```

## Task 3: Add Rich renderers for startup and result summaries

**Files:**
- Create: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_renderer.py`

- [ ] **Step 1: Expand failing tests for rendering output**

Add assertions that rendered text includes:
- project title
- missing items
- recommended commands
- recent result summary
- compare metric lines when available

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: FAIL because renderer functions do not exist or lack required output.

- [ ] **Step 3: Implement minimal renderer**

Use `rich` tables/panels to render:
- startup screen
- command help
- run summary
- error summary

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_renderer.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_renderer.py tests/test_repl_renderer.py
git commit -m "feat: add repl rich renderers"
```

## Task 4: Add REPL command handlers

**Files:**
- Create: `E:\ClaudeProject\VAD\src\app\repl_commands.py`
- Modify: `E:\ClaudeProject\VAD\src\app\orchestrator.py`
- Test: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`

- [ ] **Step 1: Write failing command-handler tests**

Cover:
- `doctor` refreshes state
- `results` loads latest result summary
- `run mini` refuses when mini inputs are missing
- `run mini` calls orchestrator with expected default paths when ready

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: FAIL because handler module does not exist yet.

- [ ] **Step 3: Implement minimal handlers**

Handlers should:
- call shared state refresh
- return structured outcomes
- use default path builders for mini/full runs
- keep `download ...` and `build mini` as recommendation-only commands in the
  first version

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_commands.py src/app/orchestrator.py tests/test_repl_shell.py
git commit -m "feat: add repl command handlers"
```

## Task 5: Add the persistent REPL shell

**Files:**
- Create: `E:\ClaudeProject\VAD\src\app\repl_shell.py`
- Modify: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`

- [ ] **Step 1: Write failing shell-loop tests**

Cover:
- startup auto-runs doctor/status rendering
- `help` prints supported commands
- `exit` ends the session
- invalid command shows friendly error

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: FAIL because shell loop is not implemented yet.

- [ ] **Step 3: Implement minimal shell loop**

Implement:
- console bootstrap
- startup render
- `input()` loop
- dispatch through parser + handlers
- graceful exit handling

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_shell.py tests/test_repl_shell.py
git commit -m "feat: add persistent repl shell"
```

## Task 6: Switch the default root entry to the REPL shell

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\cli.py`
- Modify: `E:\ClaudeProject\VAD\tests\test_unified_app_entry.py`

- [ ] **Step 1: Write failing root-entry tests**

Add a test asserting the no-subcommand callback routes to REPL launch instead of
Textual home launch.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_unified_app_entry.py -q
```

Expected: FAIL because the callback still launches the old home path.

- [ ] **Step 3: Implement the routing change**

Change root callback behavior:
- subcommand present -> unchanged
- no subcommand -> launch REPL shell

Keep direct Typer commands unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_unified_app_entry.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/cli.py tests/test_unified_app_entry.py
git commit -m "feat: make repl shell the default entry"
```

## Task 7: Add live run progress and completion summaries inside the REPL

**Files:**
- Modify: `E:\ClaudeProject\VAD\src\app\repl_shell.py`
- Modify: `E:\ClaudeProject\VAD\src\app\repl_renderer.py`
- Modify: `E:\ClaudeProject\VAD\tests\test_repl_shell.py`

- [ ] **Step 1: Write failing tests for progress-aware run output**

Cover:
- shell passes `capture_progress=True`
- monitor snapshots are rendered into run output
- completion renders compare summary automatically

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: FAIL because shell run output is not progress-aware yet.

- [ ] **Step 3: Implement minimal live-progress integration**

Use existing:
- `WorkflowMonitor`
- `QueueProgressReporter`
- orchestrator progress snapshots

Render:
- current stage
- latest tool/activity
- per-stage counts
- final result summary

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_repl_shell.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/repl_shell.py src/app/repl_renderer.py tests/test_repl_shell.py
git commit -m "feat: show live progress and run summaries in repl"
```

## Task 8: Update docs and handoff notes

**Files:**
- Modify: `E:\ClaudeProject\VAD\docs\scripts_guide.md`
- Modify: `E:\ClaudeProject\VAD\agent.md`

- [ ] **Step 1: Update script guide**

Document:
- `python agentic_vad.py` now launches the REPL console
- supported short commands
- difference between interactive shell and direct Typer subcommands

- [ ] **Step 2: Update agent handoff notes**

Describe:
- REPL shell architecture
- default entry behavior
- remaining limitations

- [ ] **Step 3: Verify docs mention new workflow correctly**

Check for:
- no stale "Textual default home" wording
- no contradictory usage instructions

- [ ] **Step 4: Commit**

```bash
git add docs/scripts_guide.md agent.md
git commit -m "docs: document repl console workflow"
```

## Task 9: Full regression verification

**Files:**
- No code changes required unless regressions appear

- [ ] **Step 1: Run focused REPL and unified-entry tests**

Run:

```bash
pytest tests/test_repl_parser.py tests/test_repl_renderer.py tests/test_repl_shell.py tests/test_unified_app_entry.py tests/test_unified_status_and_results.py tests/test_orchestrator_progress.py -q
```

Expected: PASS

- [ ] **Step 2: Run broader unified app regression tests**

Run:

```bash
pytest tests/test_tui_launcher.py tests/test_textual_home_state.py tests/test_textual_sections.py tests/test_run_monitor.py tests/test_agentic_workflow_runner.py -q
```

Expected: PASS, or update tests intentionally if the old default-launch
assumptions changed.

- [ ] **Step 3: Manual verification**

Check:
- `python agentic_vad.py` starts the REPL
- startup doctor is visible
- missing setup prints recommended commands
- `run mini` works on a ready mini dataset
- completion prints result summary

- [ ] **Step 4: Final commit if needed**

```bash
git add .
git commit -m "test: verify repl console integration"
```
