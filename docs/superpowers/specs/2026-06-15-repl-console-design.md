# Agentic VAD REPL Console Design

## Goal

Replace the current mouse-oriented Textual home screen with a keyboard-first,
server-friendly, persistent terminal console that:

- starts from `python agentic_vad.py`
- runs `doctor` automatically on launch
- shows missing models, datasets, and outputs clearly
- prints exact next-step commands for the user to execute when setup is missing
- accepts short shell-like commands such as `doctor`, `run mini`, and `results`
- runs mini/full experiments inside the console with live progress updates
- shows the latest comparison results automatically when a run completes

This keeps the project local-first and AutoDL-friendly while preserving the
existing workflow/pipeline implementation.

## Why Change

The current entry path has a mismatch between interaction style and real usage:

- the Textual home view looks interactive, but the useful workflow still mostly
  requires falling back to CLI commands
- button rendering is fragile across terminal environments
- the user does not want mouse-driven interaction
- the real need is a control console that can diagnose, recommend commands,
  execute runs, and show progress in one terminal session

The new design should feel like a focused project shell instead of a dashboard
that only partially controls the system.

## Recommended Approach

Use a persistent REPL-style console built with `rich` for rendering and a plain
`input(...)` loop for commands.

This is the recommended approach because:

- it works well in SSH, AutoDL, and ordinary terminals
- it avoids relying on mouse support or complex TUI layout engines
- it reuses the existing status/orchestrator/results layers
- it gives us strong control over progress rendering and post-run summaries

We will keep the current Typer subcommands for direct automation and debugging,
but the default `python agentic_vad.py` path will launch the REPL console
instead of the current Textual app.

## User Experience

### Launch

The user runs:

```bash
python agentic_vad.py
```

On startup the console will:

1. inspect the workspace automatically
2. render a status summary
3. list missing prerequisites
4. print recommended commands
5. wait for the next input

### Command Style

The REPL command set should use short project-shell commands:

```text
help
doctor
status
download models-core
download bootstrap
build mini
run mini
run full
run stage pipeline
results
compare
clear
exit
quit
```

The user should not need to type nested Typer command names inside the shell.

### Startup Behavior

If setup is incomplete, the console should not try to hide that fact. It should
render sections like:

- `Project Status`
- `Missing Items`
- `Recommended Commands`
- `Recent Results`

If mini is runnable but full is not, that state must be explicit. For example:

- mini experiment ready
- full dataset frames missing
- recommended next command: `run mini`

### Run Behavior

When the user enters `run mini` or `run full`, the console should:

1. validate readiness for that run
2. if requirements are missing, refuse to run and print the blocking items
3. if ready, execute the workflow inside the current process/thread boundary
4. stream live progress in the terminal
5. print a result summary automatically when complete

### Result Behavior

After a successful run the console should automatically show:

- output directory
- workflow type
- resolved stages
- agentic ROC AUC / PR AUC
- baseline ROC AUC / PR AUC when available
- deltas
- latest persisted artifact paths

## Architecture

Add a REPL-focused application layer while preserving the existing orchestrator:

```text
agentic_vad.py
src/app/
  cli.py
  orchestrator.py
  status.py
  results.py
  run_monitor.py
  repl_shell.py
  repl_commands.py
  repl_renderer.py
  repl_state.py
  repl_parser.py
```

### `src/app/repl_shell.py`

Owns the persistent command loop.

Responsibilities:

- boot the console
- run startup doctor/status refresh
- read commands
- dispatch parsed commands
- own session lifecycle such as `exit`, `clear`, and refresh behavior

### `src/app/repl_parser.py`

Parses short shell commands into structured actions.

Responsibilities:

- map text like `run mini` into a typed command object
- support aliases such as `quit` -> `exit`
- provide command validation and friendly parse errors

### `src/app/repl_commands.py`

Implements the command handlers.

Responsibilities:

- `doctor`
- `status`
- `download ...`
- `build mini`
- `run mini/full/stage`
- `results`
- `compare`

These handlers should call `orchestrator`, `status`, and `results` modules
instead of re-implementing workflow logic.

### `src/app/repl_renderer.py`

Handles all `rich` output rendering.

Responsibilities:

- render startup summary panels
- render missing-item tables
- render recommended command tables
- render live run headers
- render completion summaries
- render comparison tables

This keeps rendering decisions out of command logic.

### `src/app/repl_state.py`

Defines session-local state.

Responsibilities:

- latest workspace snapshot
- latest doctor snapshot
- last run summary
- current running flag
- current monitor reference
- command history summary if needed later

### Existing modules reused

- `status.py` remains the source of readiness checks
- `orchestrator.py` remains the source of run execution
- `run_monitor.py` remains the source of progress event accumulation
- `results.py` remains the source of persisted result loading

## Status and Recommendation Model

The REPL should distinguish between:

1. general workspace health
2. mini run readiness
3. full run readiness
4. recommended next actions

The recommendation engine should derive concrete commands from status.

Examples:

- if no core model is ready:
  - `python agentic_vad.py assets download --preset models-core`
- if mini subset is not ready:
  - `python agentic_vad.py dataset build-mini`
- if mini is ready:
  - `run mini`
- if full dataset is ready:
  - `run full`

Inside the REPL we should still show the short form first, but also print the
full external command when the user may need to run it outside the console.

## Progress Design

Progress is a first-class output in this console.

We already have:

- `ProgressEvent`
- `WorkflowMonitor`
- orchestrator support for `capture_progress=True`

The REPL should reuse that path.

### Rendering rules

During runs, render:

- current stage summary
- latest tool/task line
- per-stage completed/total counts when available
- recent event tail for context

The output should stay compact and stable in the terminal instead of printing
unbounded scrolling logs by default.

### Suggested run display

```text
Run: mini
Stage: pipeline
Latest: vlm_tool | video=Abuse028_x264 | window=000016 | caption scoring
Progress:
- pipeline: 12/40
- metrics: pending
- compare: pending
```

We can evolve this later into a continuously refreshed live panel, but the
first implementation only needs stable repeated renders plus a final summary.

## Command Execution Policy

Not every command should execute work immediately.

### Commands that should execute internally

- `doctor`
- `status`
- `run mini`
- `run full`
- `run stage ...`
- `results`
- `compare`

### Commands that should recommend external execution first

For the first version, these should mainly print the exact script command:

- `download ...`
- `build mini`

Reason:

- downloads can be long-running and are often interrupted/restarted manually
- the user explicitly wants the system to tell them what to execute
- this keeps the shell safer and easier to reason about

We can add an `execute` or `--run` mode later if needed.

## Error Handling

The console should be strict but friendly:

- unknown command -> show parse error and `help`
- missing run prerequisites -> show blockers and recommended commands
- workflow exception -> show concise error summary and preserve shell session
- Ctrl+C during idle prompt -> ask to use `exit` or treat as session exit
- Ctrl+C during run -> allow interruption and return to shell cleanly if
  practical

## Testing Strategy

This refactor must be test-driven.

Minimum new test areas:

- REPL parser accepts supported commands
- REPL parser rejects malformed commands
- startup state renders missing-item recommendations
- `run mini` command maps to the expected default dataset paths
- `run mini` blocked state reports missing readiness cleanly
- completed run summary shows compare metrics when available
- default `agentic_vad.py` path launches REPL instead of the old Textual app

We should preserve existing direct-command Typer tests.

## Migration Plan

1. Introduce the new REPL modules without removing existing CLI commands
2. Make `python agentic_vad.py` default to REPL launch
3. Keep Typer subcommands intact for automation and debugging
4. Retire or de-emphasize `tui_app.py` from the default path
5. Update docs and handoff notes

## Scope Boundaries

This design does not include:

- web UI
- browser-based dashboards
- multi-user sessions
- remote job queueing
- replacing the underlying workflow runner

It is a control-surface refactor, not a pipeline rewrite.

## Recommendation

Implement the REPL shell now and keep the current Typer command surface as the
backend API. This gives us the best balance of usability, reliability, and
incremental risk for server-side usage.
