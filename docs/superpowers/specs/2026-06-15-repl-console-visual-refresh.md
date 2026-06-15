# Agentic VAD REPL Visual Refresh Design

## Goal

Upgrade the current REPL console from a sequence of plain tables into a more
modern, research-console-style terminal interface while preserving the same
interaction model:

- persistent shell
- keyboard-only usage
- command-first workflow
- server-friendly rendering
- Rich-based output only

This is a visual and information-architecture refresh, not a change to the
core workflow execution model.

## Non-Goals

This refresh does not introduce:

- mouse interaction
- browser UI
- complex Textual layout dependency
- hidden state transitions
- replacement of the current CLI command model

The shell must remain transparent and predictable.

## Problems in the Current REPL

The current REPL works, but it still feels like a collection of independent
tables rather than a coherent console:

1. section hierarchy is weak
2. every view uses a similar table treatment, so priority is visually flat
3. there is no strong top-level identity/header
4. command hints are useful but visually ordinary
5. progress output is informative but not yet shaped like a dedicated run view
6. success, warning, and error states do not yet have a refined visual rhythm

The result is usable, but not yet "modern" in the sense of a deliberate,
professional control surface.

## Design Direction

The right visual direction is not "flashy terminal UI". It should feel like a
research operations console:

- dark, quiet, professional
- structured and dense
- explicit state hierarchy
- low-noise emphasis
- command-centric

The interface should read more like an experiment control center than a generic
admin dashboard.

## Visual Principles

### 1. Strong top bar, quiet body

Every major render should begin with a compact header band that answers:

- where am I
- what dataset mode is available
- what is the latest run status
- what environment am I in

This top bar should anchor the page and reduce the feeling that each command
output is a disconnected report.

### 2. Carded information groups, not repeated generic tables

We should stop treating every section identically.

Recommended grouping:

- status summary block
- missing items block
- recommended commands block
- result summary block
- run progress block

Each block should have a distinct visual role:

- summary blocks: panel-like
- metrics: compact table
- commands: monospace list with emphasis
- progress: structured timeline-like output

### 3. Semantic color, restrained saturation

Use color sparingly:

- `ok`: soft green
- `warn`: amber
- `error`: muted red
- `active`: cyan / blue
- structural text: grey/white

No neon-heavy palette. The target feeling is closer to a polished systems tool
than a hacker-themed terminal.

### 4. Fixed layout rhythm

Each render should follow predictable vertical rhythm:

1. header
2. overview row
3. actionable items
4. results or progress
5. prompt hint / next actions

Predictability matters more than decorative variation.

## Recommended Screen Architecture

## A. Startup / Status View

This is the most important screen because users will see it every time they
launch the shell.

### Structure

1. `Header Strip`
2. `Overview Grid`
3. `Action Queue`
4. `Recent Results`
5. `Prompt Hint`

### Header Strip

Display:

- product name: `Agentic VAD Console`
- mode tag: `REPL`
- env tag: current conda env
- dataset readiness tags: `mini ready` / `full missing`
- latest result tag if available: `last: ok`

Example:

```text
Agentic VAD Console   REPL   env: VAA   mini: ready   full: missing   last: ok
```

This should feel like a compact instrument header, not a decorative banner.

### Overview Grid

Use 4 small compact panels:

- `Environment`
- `Models`
- `Datasets`
- `Outputs`

Each panel shows 3-6 short lines, not a large table.

Example:

```text
Environment      Models           Datasets          Outputs
python 3.10.20   embedding ok     mini ready        recent compare ok
conda VAA        vlm ready        full missing      outputs present
rich ok          llm ready        captions ok       memory dir ready
```

The purpose is instant scanability.

### Action Queue

This should become the shell's visual center when setup is incomplete.

Instead of a generic "recommended commands" table, render:

- a short label like `Next Actions`
- numbered command recommendations
- one-line reason under each recommendation

Example:

```text
Next Actions
1. python agentic_vad.py assets download --preset models-core
   Missing required model assets.

2. python agentic_vad.py dataset build-mini
   Mini dataset is not ready for smoke experiments.

3. run mini
   Available after mini dataset and core assets are ready.
```

This feels more intentional than a generic command table.

### Recent Results

Present recent result status as compact metric cards or a concise summary block:

- status
- roc delta
- pr delta
- output path

This section should be concise and visually secondary unless the user ran
`results` or `compare`.

### Prompt Hint

At the bottom of the initial render, print a compact prompt helper:

```text
Try: help | doctor | run mini | compare
```

That reduces recall cost without cluttering the whole screen.

## B. Doctor View

The doctor view should feel diagnostic, not generic.

### Structure

1. header strip
2. doctor summary line
3. categorized checks

Instead of one flat table, group checks into:

- runtime
- dataset inputs
- outputs

This helps users see what kind of failure they are dealing with.

## C. Run Progress View

This is where the shell can feel significantly more modern.

The run view should not look like just another table. It should look like an
active execution console.

### Structure

1. `Run Header`
2. `Current Activity`
3. `Stage Progress`
4. `Recent Events`
5. `Completion Summary` once done

### Run Header

Display:

- workflow kind: mini/full
- status: running/done/failed
- stage count summary

Example:

```text
Run: mini   Status: running   Stages: pipeline -> metrics -> compare
```

### Current Activity

Highlight one active line with emphasis:

```text
Active: pipeline | vlm_tool | caption scoring
```

This should be the single most visually prominent line in the run block.

### Stage Progress

Render each stage on its own line:

```text
pipeline   12/40
metrics    pending
compare    pending
```

Use subtle symbols or color states:

- running stage highlighted
- completed stage dim green
- pending stage dim grey

### Recent Events

The current events table is useful, but we should tighten it visually:

- keep only the last 3-5 events
- use narrower columns
- emphasize tool/event column

This should read like a short execution tail, not a full log dump.

### Completion Summary

After the run finishes, show:

- compare status
- roc delta
- pr delta
- workflow summary path if available

This should immediately follow the progress block so the user's visual flow is
"watch run -> see outcome" without a context switch.

## D. Results / Compare Views

These should become tighter and more publication-aware.

Instead of generic field/value tables everywhere, use:

- top status strip
- compact metrics section
- delta-focused summary

Recommended metric layout:

```text
ROC AUC   +0.2350
PR AUC    -0.4229
Status    ok
```

The core question is comparison quality, so deltas deserve visual priority.

## Command Prompt Styling

The prompt itself should become more informative.

Current style:

```text
agentic-vad>
```

Recommended style:

```text
agentic-vad [mini:ready full:missing] >
```

Or a shorter version:

```text
avad [mini+] [full-] >
```

I recommend the first version because it is clearer and still compact.

## Implementation Approach

This refresh should stay inside `src/app/repl_renderer.py` and
`src/app/repl_shell.py` as much as possible.

### Recommended renderer refactor

Split current rendering into higher-level builders:

- `render_console_header(...)`
- `render_overview_cards(...)`
- `render_action_queue(...)`
- `render_recent_result_block(...)`
- `render_doctor_sections(...)`
- `render_run_activity(...)`
- `render_run_stage_progress(...)`
- `render_recent_events(...)`

This keeps the code maintainable and makes visual refinement incremental.

## Incremental Rollout Plan

### Phase 1: Startup modernization

Refresh:

- top header strip
- overview grid
- action queue
- prompt hint

### Phase 2: Doctor/results modernization

Refresh:

- doctor section grouping
- result summary compact cards
- compare summary compact cards

### Phase 3: Run experience modernization

Refresh:

- active run header
- stage progress layout
- recent events tail
- completion summary coupling

### Phase 4: Prompt ergonomics

Optionally add:

- contextual prompt text
- better command helper line
- shell footer reminders

## Recommendation

Implement this as a Rich-only visual refactor in the existing REPL shell.

Do not switch back toward Textual for this goal. The "modernity" we want is
clarity, hierarchy, and polish, not a more fragile rendering stack.
