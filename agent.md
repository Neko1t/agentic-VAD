# Agent Handoff Notes

## Project Context

This repository implements video anomaly detection / understanding code from an
open-source research project. The current refactor direction is to evolve the
existing script-like VAD workflow into a lightweight, local-first, multi-agent
Agentic VAD framework.

Important directories:

- `data/`: dataset files, annotations, extracted frames, captions, scores, and
  generated memory/output artifacts.
- `libs/`: local LLM/VLM model code and weights. It is currently mostly empty
  except placeholder/model code. Large model checkpoints should live here later.
- `src/`: main code.
- `tests/`: unit tests for schemas, tools, memory, and agent behavior.
- `docs/`: longer implementation notes. One existing Chinese plan file appears
  to have encoding mojibake and should be fixed later.

Current design docs in the project root:

- `agentic_vad_architecture.md`: high-level multi-agent architecture.
- `agent_communication_schema_design.md`: proposed Pydantic communication
  schemas and memory event design.
- `agentic_vad_schema_implementation_flow.md`: phased implementation plan for
  schema, memory policy, agent process method, pipeline refactor, and tests.

This `agent.md` is the quick-start handoff document for future sessions.

## Current Code Structure

Key packages:

- `src/core`
  - `schemas.py`: current Pydantic models such as `WindowInput`,
    `ObservationCard`, `EpisodeSummary`, `CaseMemoryRecord`,
    `RetrievalResult`, and `CalibrationResult`.
  - `config.py`: pipeline, scoring, and memory config.

- `src/agents`
  - `perception_agent.py`: `PerceptionAgent`, which calls VLM/audio/OCR/scoring
    tools and returns an `ObservationCard`.
  - `story_memory_agent.py`: `StoryMemoryAgent`, which updates rolling context,
    retrieves memory, calibrates score, and returns `StoryMemoryResult`.

- `src/runtime`
  - `progress.py`: runtime progress event schema plus single-line Rich progress
    reporter used by the end-to-end workflow runner.

- `src/tools`
  - `vlm_tool.py`: currently reads precomputed captions and extracts simple
    entities/actions. It should later become a backend-based VLM adapter.
  - `audio_tool.py`: optional audio tool, currently lightweight.
  - `ocr_tool.py`: optional OCR tool, currently lightweight.
  - `score_tool.py`: heuristic local scoring and retrieval-guided score fusion.
  - `rag_tool.py`: wrapper around case and pattern memory stores.

- `src/memory`
  - `case_store.py`: JSONL + optional Chroma-backed case memory store.
  - `pattern_store.py`: simple JSONL pattern prototype store.
  - `embedding_builder.py`: sentence-transformers embedding wrapper with a
    deterministic fallback.

- `src/pipelines`
  - `run_agentic_vad.py`: current agentic prototype pipeline. It loads videos,
    builds windows, calls agents, executes memory events, exports eval-ready
    scores, and emits fine-grained progress events.
  - `run_agentic_workflow.py`: end-to-end workflow runner that can execute
    `pipeline -> promote -> patterns -> metrics -> compare` in one command or
    run selected stages independently for debugging.
  - `build_case_memory.py`: imports episode outputs into memory.
  - `extract_patterns_offline.py`: extracts pattern prototypes from finalized
    case memory.

## Current Prototype Behavior

The current prototype now has the first communication-schema refactor in place:

```text
WindowInput
  -> PerceptionAgent
  -> ObservationCard
  -> StoryMemoryAgent.process(StoryMemoryInput)
  -> StoryMemoryResult
  -> MemoryWriteEvent
  -> Pipeline executes allowed memory writes
  -> DecisionReport
```

Implemented in the first development pass:

- `RunMode`, `ToolCallRecord`, `MemoryWriteDecision`, `MemoryCaseType`,
  `MemoryWriteEvent`, `StoryMemoryInput`, and `StoryMemoryResult` were added to
  `src/core/schemas.py`.
- `ObservationCard` now supports optional `tool_trace`.
- `CaseMemoryRecord` now has optional memory-policy metadata such as
  `case_type`, `source`, `uncertainty`, `local_score`, `final_score`,
  retrieval IDs, matched pattern IDs, and `hit_count`.
- `src/memory/policy.py` implements `MemoryPolicy`.
- `StoryMemoryAgent.process(...)` returns `StoryMemoryResult` while
  `summarize_episode(...)` remains for compatibility.
- `run_agentic_vad.py` now uses `StoryMemoryInput` / `StoryMemoryResult`,
  executes `MemoryWriteEvent`, and persists `story_results`.
- `VLMTool` now supports backend adapters while keeping the old
  `VLMTool(captions_dir=...)` call style:
  - `PrecomputedCaptionBackend`
  - `CallableCaptionBackend`
  - `MockVLMBackend`
  - `NullVLMBackend`
- `PerceptionAgent` now records `ToolCallRecord` entries for VLM, audio, OCR,
  and scoring in `ObservationCard.tool_trace`.
- `src/memory/session_store.py` implements in-memory current-run session memory.
  It retrieves only cases matching the current `video_id`, so provisional cases
  can help later windows in the same video without becoming cross-video memory.
- `RAGTool` can now merge persistent finalized case memory with optional session
  memory retrieval.
- `run_agentic_vad.py` now writes accepted online memory events to both session
  memory and persistent provisional case memory.
- `src/memory/promotion.py` implements offline promotion rules for provisional
  memory.
- `src/pipelines/promote_case_memory.py` provides a CLI/function for dry-run and
  actual promotion of eligible provisional cases.
- `run_agentic_vad.py` exposes a `use_chroma` switch for lightweight local and
  test runs.
- Tests include a tiny mocked end-to-end pipeline run that verifies reports,
  observations, episodes, story results, tool traces, and provisional memory
  artifacts.
- `PerceptionAgent` tool execution now captures `latency_ms` and `error` in
  `ToolCallRecord`. Failed tools fall back to safe low-information outputs while
  preserving the error string in the trace.
- `run_agentic_vad.py` now exports original-eval-compatible score JSON files
  under `output_dir/scores/`, using the current observation window start frame
  as the key and normalized `final_score` as the value.
- `src/eval/agentic_vad_metrics.py` can run the original `ROC AUC / PR AUC`
  evaluator directly on agentic-exported scores.
- `src/pipelines/run_agentic_workflow.py` can now run the complete system with
  a single-line dynamic progress bar, stage selection, metric export, and
  optional baseline comparison.
- `pytest.ini` now sets `pythonpath = .` and uses a project-local pytest temp
  directory.

Remaining limitation:

- A real VideoLLaMA backend is not implemented yet.

## Target Architecture

The target architecture is:

```text
Pipeline Orchestrator
  |
  | WindowInput
  v
PerceptionAgent
  |-- VLMTool
  |-- AudioTool
  |-- OCRTool
  |-- ScoreTool
  |
  | ObservationCard
  v
StoryMemoryAgent
  |-- Rolling context update
  |-- RAGTool retrieval
  |-- Score calibration
  |-- MemoryPolicy
  |
  | StoryMemoryResult
  v
Pipeline / Memory Service
  |-- persist observations
  |-- persist episodes
  |-- persist story results
  |-- execute MemoryWriteEvent
  |-- write DecisionReport
```

The pipeline should be thin. It should iterate data, call agents, persist
artifacts, and execute memory events. It should not implement anomaly reasoning,
score fusion, retrieval decisions, or case-memory construction rules.

## Design Responsibilities

### Pipeline Orchestrator

Responsibilities:

- Load annotation files and build `WindowInput`.
- Call `PerceptionAgent.process_window`.
- Maintain the recent observation buffer.
- Build `StoryMemoryInput`.
- Call `StoryMemoryAgent.process`.
- Persist observations, episodes, story results, and final reports.
- Execute `MemoryWriteEvent` by calling `rag_store` when allowed.

Non-responsibilities:

- Do not build `CaseMemoryRecord` directly.
- Do not decide whether an episode deserves memory storage.
- Do not implement retrieval or score fusion rules.

### PerceptionAgent

Input:

- `WindowInput`

Tools:

- `VLMTool`
- `AudioTool`
- `OCRTool`
- `ScoreTool`

Output:

- `ObservationCard`

Boundary:

- It may describe visible local facts, entities, actions, scene context,
  modality confidence, uncertainty, and first-pass score.
- It must not perform long-term story reasoning, RAG comparison, final abnormal
  decision-making, or memory writes.

### StoryMemoryAgent

Input:

- `StoryMemoryInput`, containing previous `RollingSummaryState` and recent
  `ObservationCard` objects.

Tools/services:

- `RAGTool`
- `ScoreTool` or future calibration tool
- `MemoryPolicy`

Output:

- `StoryMemoryResult`

Responsibilities:

- Update rolling temporal context.
- Generate an `EpisodeSummary`.
- Build retrieval query from action sequence, scene, evidence tags, and story.
- Retrieve similar cases and matched patterns.
- Calibrate local, story, and memory-adjusted scores.
- Produce contradiction/disagreement signals.
- Ask `MemoryPolicy` for a `MemoryWriteEvent`.

### MemoryPolicy

Purpose:

- Own memory admission rules.
- Build `CaseMemoryRecord` when a case should be stored.
- Return a structured `MemoryWriteEvent`.

Key rules:

- Online writes are always `provisional=True`.
- `OFFLINE_EVAL` mode must skip writes.
- High-confidence high-risk cases can be stored as `HIGH_RISK`.
- High-local-score but low-final-score cases should be stored as
  `HARD_NEGATIVE`.
- Near-duplicate cases should be skipped or update existing metadata rather than
  create another vector.
- Finalized promotion should happen offline, not during normal inference.

### Memory Stores

- `RollingSummaryState`: short-term in-memory state for the current video.
- `SessionMemoryStore`: current-video retrieval without polluting long-term
  memory. It is in-memory and scoped by `video_id`.
- `CaseMemoryStore`: persistent cross-video case memory. Retrieval should use
  finalized cases by default.
- `PatternMemoryStore`: offline patterns extracted from stable/finalized case
  memory.

## Communication Schema Plan

Add these schemas to `src/core/schemas.py` during the next implementation pass:

- `RunMode`
  - `offline_eval`
  - `online_inference`
  - `memory_building`
  - `debug_replay`

- `ToolCallRecord`
  - lightweight tool trace with summaries, confidence, latency, error, and
    artifact references.

- `MemoryWriteDecision`
  - `write`
  - `skip`
  - `update_existing`

- `MemoryCaseType`
  - `high_risk`
  - `hard_negative`
  - `ambiguous`
  - `routine`

- `MemoryWriteEvent`
  - decision, case type, reason, skip codes, optional case record, duplicate
    information, similarity to existing memory.

- `StoryMemoryInput`
  - video id, rolling state, recent observations, top-k, run mode.

- `StoryMemoryResult`
  - episode, updated state, retrieval result, calibration result, memory event,
    disagreement score, contradiction flags, tool trace.

Also add optional `tool_trace` to `ObservationCard` with a default empty list.
Keep existing fields unchanged for compatibility.

## Implementation Flow

Recommended order:

1. Update `src/core/schemas.py`.
2. Extend `tests/test_schemas.py`.
3. Add `src/memory/policy.py`.
4. Add `tests/test_memory_policy.py`.
5. Add `StoryMemoryAgent.process(...)` in `src/agents/story_memory_agent.py`.
6. Extend `tests/test_story_memory_agent.py`.
7. Refactor `src/pipelines/run_agentic_vad.py` to use
   `StoryMemoryInput`/`StoryMemoryResult`.
8. Add pipeline contract tests using mocked tools.
9. Update `pytest.ini` with `pythonpath = .`.

Keep backward compatibility during the first pass:

- Do not remove existing schema fields.
- Keep `StoryMemoryAgent.summarize_episode(...)`.
- Keep current output folders: `observations`, `episodes`, `reports`.
- Add a new output folder: `story_results`.
- Keep `CaseMemoryStore` retrieval behavior unchanged initially.

## Testing Notes

Observed test baseline:

- `pytest -q` may fail in some environments because `src` is not on
  `PYTHONPATH`.
- `$env:PYTHONPATH='.'; pytest -q` passes the current 5 tests.

Recommended `pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

Tests to add:

- Schema defaults for new communication objects.
- MemoryPolicy high-risk write.
- MemoryPolicy hard-negative write.
- MemoryPolicy offline-eval skip.
- StoryMemoryAgent returns full `StoryMemoryResult`.
- Pipeline no longer directly constructs `CaseMemoryRecord`.
- Workflow runner stage selection and metric comparison outputs.

## Design Decisions To Preserve

- Use direct Pydantic objects first. Defer `AgentEnvelope` until async queues,
  multi-process execution, or full replay logs are needed.
- Keep memory proposal separate from persistence:
  `StoryMemoryAgent -> MemoryWriteEvent`, then pipeline/memory service executes.
- Do not store full prompts, full raw model outputs, or large frame payloads in
  `ToolCallRecord`; store summaries, hashes, and artifact references.
- Keep heuristic scoring as a deterministic baseline even after adding
  model-based scoring.
- Keep local-first implementation. Do not introduce LangChain/LlamaIndex unless
  there is a clear need.

## Model Backend Lifecycle Rules

All future real model backends, especially `VideoLLaMABackend` and any
LLM-based scorer, must follow these rules to reduce GPU memory risk:

- Load each heavy model once per backend instance. Do not load models inside
  every window-level `describe(...)` or scoring call.
- Run inference under `torch.inference_mode()` or `torch.no_grad()`.
- Convert GPU tensors to CPU/Python values before returning from backend calls.
- Never store GPU tensors in `ObservationCard`, `StoryMemoryResult`,
  `ToolCallRecord`, `MemoryStore`, or JSON artifacts.
- Keep `ToolCallRecord` lightweight: summaries, confidence, latency, error, and
  artifact refs only.
- Provide an explicit `close()` or `unload()` method for any backend that owns
  GPU resources.
- Pipeline shutdown may call `torch.cuda.empty_cache()` after backend unload, but
  this should be treated as cleanup, not as the primary memory-management
  strategy.
- Avoid loading separate VLM/LLM/embedding GPU models in multiple agents unless
  resource ownership is deliberate and documented.

## Near-Term TODO

- Add real `VideoLLaMABackend` once local model files are available under
  `libs/`.
- Decide whether to add a real baseline `scores_dir` preset for automated
  comparison against the original author pipeline on each dataset.
- When adding a new script or executable entrypoint, update `scripts_guide.md`
  in the same change so the usage guide stays current.

After this, the project will have a clean agent communication layer suitable
for real VLM backend integration, LLM-based story reasoning, session memory,
and offline memory promotion.
