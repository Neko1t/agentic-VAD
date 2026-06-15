# Agentic VAD Architecture Notes

## 1. Goal

The next-stage refactor aims to turn the current VAD pipeline into a lightweight
multi-agent research framework. The key design goal is decoupling:

- The perception-side agent observes video windows and produces first-pass
  structured evidence and anomaly scores.
- The story-memory-side agent consumes perception evidence, summarizes temporal
  context, retrieves related memory, calibrates risk, and decides what should be
  written into local memory.
- The pipeline orchestrator only controls dataset iteration, window scheduling,
  agent invocation, and artifact persistence. It should not contain anomaly
  reasoning or memory construction rules.

The initial implementation should remain native Python and local-first. We do
not need LangChain or a heavy agent framework at this stage.

## 2. High-Level Architecture

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
  |-- Summary / Context logic
  |-- RAGTool
  |-- Score calibration
  |-- MemoryPolicy
  |
  | StoryMemoryResult
  v
Memory / Reports
  |-- CaseMemoryStore
  |-- PatternMemoryStore
  |-- Session artifacts
  |-- DecisionReport
```

## 3. Core Responsibilities

### Pipeline Orchestrator

The pipeline should be deliberately thin.

Responsibilities:

- Load dataset annotations and build `WindowInput`.
- Call `PerceptionAgent.process_window`.
- Maintain recent observation buffers.
- Call `StoryMemoryAgent.process`.
- Persist observations, episodes, memory events, and final reports.

Non-responsibilities:

- It should not build `CaseMemoryRecord` directly.
- It should not decide which episode is worth storing.
- It should not implement score fusion or retrieval rules.

### PerceptionAgent

The perception agent owns local window-level observation.

Input:

- `WindowInput`

Tools:

- `VLMTool`
- `AudioTool`
- `OCRTool`
- `ScoreTool`

Output:

- `ObservationCard`

Expected behavior:

- Gather multimodal evidence.
- Normalize raw tool outputs into a structured schema.
- Produce first-pass `score_raw`, `score_weighted`, `uncertainty`, and
  `reason_trace`.
- Avoid knowing anything about long-term memory or final video-level decisions.

### StoryMemoryAgent

The story-memory agent owns temporal context and memory interaction.

Input:

- Previous `RollingSummaryState`
- Recent `ObservationCard` objects

Tools / services:

- `RAGTool`
- `ScoreTool` or future calibration tool
- `MemoryPolicy`

Output:

- `StoryMemoryResult`

Expected behavior:

- Update rolling temporal context.
- Generate `EpisodeSummary`.
- Build retrieval query from action sequence, scene, tags, and story text.
- Retrieve related case and pattern memory.
- Calibrate local risk using story and retrieval evidence.
- Decide whether a case memory record should be proposed.

The agent may propose a memory write, but the actual write can remain in the
pipeline or a memory service. This keeps writing policy testable and allows
future asynchronous or human-reviewed memory updates.

## 4. Proposed Schemas

The current schemas are a good foundation. The next refactor should add explicit
result and trace schemas.

```python
class ToolCallRecord(BaseModel):
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    confidence: float | None = None
    latency_ms: float | None = None
    error: str | None = None


class MemoryWriteEvent(BaseModel):
    should_write: bool
    reason: str = ""
    case_record: CaseMemoryRecord | None = None


class StoryMemoryResult(BaseModel):
    episode: EpisodeSummary
    state: RollingSummaryState
    retrieval: RetrievalResult
    calibration: CalibrationResult
    memory_event: MemoryWriteEvent | None = None
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
```

These schemas make agent-to-agent communication easier to inspect, replay, and
test.

## 5. Memory Design

The memory system should distinguish short-term context from long-term learned
cases.

```text
RollingSummaryState
  Current video-level temporal state. Lightweight, in-memory, updated every
  window or every episode.

SessionMemoryStore
  Optional current-video memory. Useful for intra-video retrieval without
  polluting long-term memory.

CaseMemoryStore
  Persistent cross-video case memory. Stores structured case JSONL plus vector
  index. Should prefer finalized or reviewed records for retrieval.

PatternMemoryStore
  Offline pattern prototypes extracted from stable case memory.
```

The current `provisional` field is useful and should remain. A recommended
policy:

- High-risk auto-generated cases are stored as provisional.
- Provisional cases are not used for cross-video retrieval by default.
- A later promotion step can mark selected cases as finalized.
- Session memory can still use provisional cases within the current video.

## 6. MemoryPolicy

Move case construction out of the pipeline and into a dedicated policy object.

```python
class MemoryPolicy:
    def build_case_record(
        self,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
    ) -> CaseMemoryRecord | None:
        ...
```

The policy should own:

- Storage threshold.
- Provisional/finalized rule.
- Evidence tag extraction.
- Case ID construction.
- Embedding text construction.
- Label assignment.

This keeps memory behavior consistent across online pipeline runs, offline
imports, and future evaluation scripts.

## 7. VLM Tool Backend Strategy

The current `VLMTool` reads precomputed captions, which is useful for fast
offline experimentation. For the multi-agent design, the tool should expose a
stable interface while supporting multiple backends.

```text
VLMTool
  |
  |-- PrecomputedCaptionBackend
  |-- VideoLLaMABackend
  |-- MockVLMBackend
```

This allows the perception agent to stay unchanged when switching from
precomputed caption files to true frame-level VLM inference.

## 8. Development Phases

### Phase 1: Contract Cleanup

- Add `StoryMemoryResult`.
- Add `MemoryWriteEvent`.
- Add `ToolCallRecord`.
- Add `MemoryPolicy`.
- Move `_build_case_record` logic out of the pipeline.
- Fix test import path in `pytest.ini`.

### Phase 2: Agent Boundary Tests

- Test that `PerceptionAgent` only outputs `ObservationCard`.
- Test that `StoryMemoryAgent` returns `StoryMemoryResult`.
- Test that memory write decisions are produced by `MemoryPolicy`.
- Test that the pipeline can run with mocked tools and no model dependencies.

### Phase 3: Backend Refactor

- Split `VLMTool` into interface plus backend adapters.
- Keep precomputed captions as the default backend.
- Add mock backend for deterministic tests.
- Add real VideoLLaMA backend later.

### Phase 4: Memory Maturation

- Add optional `SessionMemoryStore`.
- Keep provisional and finalized long-term memories separated.
- Add promotion utilities for provisional cases.
- Improve pattern extraction from finalized cases only.

### Phase 5: Model-Based Reasoning

- Replace or supplement heuristic scoring with LLM-based scoring.
- Add prompt templates for story summarization and abnormal tag extraction.
- Keep heuristic scoring as a deterministic baseline.

## 9. Immediate Next Step

The most useful next implementation step is Phase 1:

1. Add result/trace schemas.
2. Add `MemoryPolicy`.
3. Refactor `StoryMemoryAgent.summarize_episode` into a higher-level
   `StoryMemoryAgent.process`.
4. Simplify `run_agentic_vad.py` so it only orchestrates agent calls and writes
   artifacts.

This will turn the current prototype from an agent-flavored pipeline into a
cleaner multi-agent base that is easier to extend with real VLM and LLM tools.

## 10. Model Backend Lifecycle Rules

Future real model backends are the main GPU-memory risk area. Any
`VideoLLaMABackend`, LLM scorer, or GPU embedding backend should follow these
rules:

- Heavy models should be initialized once per backend instance, not once per
  video window.
- Inference should run under `torch.inference_mode()` or `torch.no_grad()`.
- Backends should return CPU/Python summaries, not GPU tensors.
- GPU tensors must not be stored in Pydantic schemas, memory stores, traces, or
  JSON artifacts.
- Tool traces should stay lightweight: summaries, confidence, latency, error,
  and artifact references only.
- Backends that own GPU resources should expose `close()` or `unload()`.
- Pipeline-level cleanup may call `torch.cuda.empty_cache()` after unloading,
  but correctness must not rely on cache clearing.
- If multiple GPU models are loaded at once, ownership and expected memory usage
  should be explicit in config or backend documentation.
