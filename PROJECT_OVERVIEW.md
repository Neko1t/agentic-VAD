# Project Overview

This file is the fastest entrypoint for a new session.

## What This Repository Is

This repository started from the open-source `URF-HVAA` codebase and now
contains an `agentic-vad` branch of work that restructures temporal video
anomaly detection into a lightweight multi-agent system.

Current core idea:

- `PerceptionAgent` handles local caption-driven observation and first-pass
  scoring.
- `StoryMemoryAgent` handles rolling context, retrieval, calibration, and
  memory-write proposals.
- The pipeline exports original-eval-compatible temporal scores so we can
  compare against the author baseline using `ROC AUC / PR AUC`.

## Current Status

- The end-to-end agentic workflow runs.
- A mini UCF-Crime subset builder exists for fast smoke experiments.
- Asset download helpers exist for models and dataset staging.
- Real `VideoLLaMABackend` integration is still pending.

## Main Entry Points

- Agentic workflow:
  - `scripts/run_agentic_workflow.sh`
  - `scripts/run_agentic_workflow_ucf_crime.sh`
  - `scripts/run_agentic_workflow_xd_violence.sh`
- Asset download:
  - `scripts/download_agentic_assets.sh`
  - `scripts/download_agentic_assets.py`
- Mini subset build:
  - `scripts/build_ucf_crime_mini_subset.sh`
  - `scripts/build_ucf_crime_mini_subset.py`

## Recommended Reading Order

1. `README.md`
2. `agent.md`
3. `docs/scripts_guide.md`
4. `docs/agentic_vad_workflow.md`
5. `docs/original_project_evaluation.md`

## Current Experiment Path

For the current agentic smoke path:

1. Stage assets and models
2. Build a small dataset subset if needed
3. Run:

```bash
./scripts/run_agentic_workflow.sh --stage pipeline --stage metrics --stage baseline-metrics --stage compare --no-use-chroma
```

## Important Constraints

- The current default VLM path still uses precomputed caption JSON files.
- Real model downloads do not automatically mean the runtime is already wired to
  consume them.
- Generated data under `data/` is local/runtime state and should not be treated
  as source-controlled project content.

## Document Map

- `docs/README.md`: document index
- `docs/scripts_guide.md`: script usage
- `docs/agentic_vad_architecture.md`: high-level architecture
- `docs/agentic_vad_workflow.md`: runtime flow
- `docs/agent_communication_schema_design.md`: schema design
- `docs/agentic_vad_schema_implementation_flow.md`: implementation phases
- `docs/agentic_vad_runtime_logic.md`: detailed runtime notes
- `docs/original_project_evaluation.md`: baseline evaluation notes
