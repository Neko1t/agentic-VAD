# Agentic VAD Schema Implementation Flow

## 1. Purpose

This document describes how to implement the agent communication schema design
for the next-stage Agentic VAD refactor.

The goal is not to rewrite the whole repository at once. The goal is to add a
stable communication layer first, then gradually move reasoning and memory
policy out of the pipeline.

## 2. Target End State

The desired runtime flow is:

```text
Pipeline
  builds WindowInput
  |
  v
PerceptionAgent.process_window(window)
  returns ObservationCard
  |
  v
StoryMemoryAgent.process(StoryMemoryInput)
  returns StoryMemoryResult
  |
  v
Pipeline / Memory Service
  persists observations
  persists episodes
  persists story-memory results
  executes MemoryWriteEvent when allowed
  builds DecisionReport
```

The pipeline should no longer build `CaseMemoryRecord` directly. It should only
execute or persist decisions produced by the agent and memory policy.

## 3. Implementation Phases

### Phase 1: Extend Core Schemas

File:

- `src/core/schemas.py`

Add:

- `RunMode`
- `ToolCallRecord`
- `MemoryWriteDecision`
- `MemoryCaseType`
- `MemoryWriteEvent`
- `StoryMemoryInput`
- `StoryMemoryResult`

Also consider adding optional trace/provenance fields to existing schemas.

Recommended additions:

```python
class RunMode(str, Enum):
    OFFLINE_EVAL = "offline_eval"
    ONLINE_INFERENCE = "online_inference"
    MEMORY_BUILDING = "memory_building"
    DEBUG_REPLAY = "debug_replay"


class ToolCallRecord(BaseModel):
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    error: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)


class MemoryWriteDecision(str, Enum):
    WRITE = "write"
    SKIP = "skip"
    UPDATE_EXISTING = "update_existing"


class MemoryCaseType(str, Enum):
    HIGH_RISK = "high_risk"
    HARD_NEGATIVE = "hard_negative"
    AMBIGUOUS = "ambiguous"
    ROUTINE = "routine"


class MemoryWriteEvent(BaseModel):
    decision: MemoryWriteDecision
    case_type: MemoryCaseType | None = None
    reason: str = ""
    skip_codes: list[str] = Field(default_factory=list)
    case_record: CaseMemoryRecord | None = None
    duplicate_of: str | None = None
    similarity_to_existing: float | None = Field(default=None, ge=0.0, le=1.0)


class StoryMemoryInput(BaseModel):
    video_id: str
    state: RollingSummaryState
    recent_observations: list[ObservationCard]
    top_k: int = Field(default=5, ge=1)
    run_mode: RunMode = RunMode.ONLINE_INFERENCE


class StoryMemoryResult(BaseModel):
    video_id: str
    episode: EpisodeSummary
    state: RollingSummaryState
    retrieval: RetrievalResult
    calibration: CalibrationResult
    memory_event: MemoryWriteEvent | None = None
    disagreement_score: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction_flags: list[str] = Field(default_factory=list)
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
```

Compatibility rule:

- Do not remove current fields from existing schemas in the first pass.
- Keep `ObservationCard.score_raw`, `score_weighted`, `uncertainty`, and
  `reason_trace` unchanged.
- If `ObservationCard.tool_trace` is added, give it a default empty list so
  existing tests and JSON files remain compatible.

### Phase 2: Add MemoryPolicy

File:

- `src/memory/policy.py`

Purpose:

- Move memory write decision logic out of `run_agentic_vad.py`.
- Convert `EpisodeSummary`, `RollingSummaryState`, `CalibrationResult`,
  observations, and retrieval results into a `MemoryWriteEvent`.

Suggested interface:

```python
class MemoryPolicy:
    def __init__(
        self,
        write_threshold: float = 8.0,
        hard_negative_local_threshold: float = 7.0,
        hard_negative_final_threshold: float = 3.0,
        uncertainty_threshold: float = 0.3,
        duplicate_similarity_threshold: float = 0.95,
    ):
        ...

    def decide(
        self,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
        observations: list[ObservationCard],
        retrieval: RetrievalResult,
        run_mode: RunMode,
    ) -> MemoryWriteEvent:
        ...
```

Initial gating logic:

1. If `run_mode == OFFLINE_EVAL`, return `SKIP` with
   `skip_codes=["eval_mode_no_write"]`.
2. If semantic duplicate is detected, return `UPDATE_EXISTING` or `SKIP`.
3. If `final_score >= 8.0` and uncertainty is low, write `HIGH_RISK`.
4. If `score_local >= 7.0` and `final_score <= 3.0`, write `HARD_NEGATIVE`.
5. If scores disagree strongly and the segment is informative, write
   `AMBIGUOUS` as provisional.
6. Otherwise return `SKIP`.

Case construction should live here:

- `case_id`
- `label`
- `risk_score`
- `evidence_tags`
- `embedding_text`
- `provisional`
- `case_type`

Important rule:

- Online writes should always be `provisional=True`.
- Finalization should happen in a separate offline promotion step.

### Phase 3: Add StoryMemoryAgent.process

File:

- `src/agents/story_memory_agent.py`

Keep existing method:

- `summarize_episode(...)`

Add new method:

```python
def process(self, story_input: StoryMemoryInput) -> StoryMemoryResult:
    ...
```

Process steps:

1. Validate `recent_observations` is non-empty.
2. Call existing `summarize_episode(...)` to preserve current behavior.
3. Retrieve cases and patterns.
4. Calibrate scores.
5. Compute disagreement and contradiction flags.
6. Call `MemoryPolicy.decide(...)`.
7. Return `StoryMemoryResult`.

Implementation note:

- The current `summarize_episode(...)` already performs retrieval and
  calibration internally. To avoid duplicate retrieval in the first pass, either:
  - refactor internals into helper methods, or
  - let `process(...)` duplicate minimal logic temporarily and remove the old
    path later.

Recommended cleaner approach:

- Extract private helpers:
  - `_build_story_text(...)`
  - `_build_retrieval_query(...)`
  - `_compute_story_score(...)`
  - `_build_episode(...)`

Then both `summarize_episode(...)` and `process(...)` can share the same logic.

### Phase 4: Refactor Pipeline

File:

- `src/pipelines/run_agentic_vad.py`

Changes:

- Remove or deprecate `_build_case_record(...)`.
- Build `StoryMemoryInput`.
- Call `story_agent.process(...)`.
- Append `result.episode`.
- Update state from `result.state`.
- Execute memory writes based on `result.memory_event`.
- Persist full `StoryMemoryResult` artifacts in a new output directory.

Proposed loop shape:

```python
observation = perception_agent.process_window(window)
observations.append(observation)

story_input = StoryMemoryInput(
    video_id=window.video_id,
    state=state,
    recent_observations=observations[-config.rolling_window_size:],
    top_k=config.memory.top_k,
    run_mode=config.run_mode,
)
story_result = story_agent.process(story_input)

state = story_result.state
episodes.append(story_result.episode)
story_results.append(story_result)

if story_result.memory_event and story_result.memory_event.case_record:
    if story_result.memory_event.decision == MemoryWriteDecision.WRITE:
        rag_tool.rag_store(story_result.memory_event.case_record)
```

### Phase 5: Improve Reports

File:

- `src/pipelines/run_agentic_vad.py`

Current report generation can remain, but it should use `StoryMemoryResult`
instead of only `EpisodeSummary`.

Recommended report inputs:

- `ObservationCard`
- `StoryMemoryResult`

Useful report fields:

- final segment score
- local score
- memory-adjusted score
- contradiction flags
- retrieved case IDs
- matched pattern IDs
- memory write decision

### Phase 6: Tests

Files:

- `tests/test_schemas.py`
- `tests/test_story_memory_agent.py`
- `tests/test_memory_policy.py`
- `tests/test_agentic_pipeline_contract.py`

Required tests:

1. Schema defaults:
   - `ToolCallRecord`
   - `MemoryWriteEvent`
   - `StoryMemoryResult`

2. Memory policy high-risk:
   - high final score
   - low uncertainty
   - returns `WRITE` and `HIGH_RISK`

3. Memory policy hard negative:
   - high local score
   - low final score
   - returns `WRITE` and `HARD_NEGATIVE`

4. Memory policy eval mode:
   - any candidate in `OFFLINE_EVAL`
   - returns `SKIP`

5. Story agent contract:
   - returns `StoryMemoryResult`
   - updates state
   - includes retrieval and calibration
   - returns a memory event

6. Pipeline contract with mocked tools:
   - produces observations
   - produces episodes
   - produces story results
   - does not directly construct case memory in the pipeline

Also update:

- `pytest.ini`

Recommended:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

## 4. Backward Compatibility Plan

To avoid breaking the current prototype:

- Keep `ObservationCard` existing fields.
- Keep `StoryMemoryAgent.summarize_episode(...)` during the first refactor.
- Keep current output folders:
  - `observations`
  - `episodes`
  - `reports`
- Add a new folder:
  - `story_results`
- Keep `CaseMemoryStore` retrieval behavior unchanged at first.

Only after tests pass should we remove duplicated helper logic from the old
pipeline path.

## 5. Recommended File-Level Change Order

1. `src/core/schemas.py`
2. `tests/test_schemas.py`
3. `src/memory/policy.py`
4. `tests/test_memory_policy.py`
5. `src/agents/story_memory_agent.py`
6. `tests/test_story_memory_agent.py`
7. `src/pipelines/run_agentic_vad.py`
8. `tests/test_agentic_pipeline_contract.py`
9. `pytest.ini`

This order keeps every step testable and reduces the chance of a broad
pipeline break.

## 6. Design Decisions To Keep Explicit

### Direct Objects vs Message Envelope

Use direct Pydantic objects first:

- `ObservationCard`
- `StoryMemoryInput`
- `StoryMemoryResult`

Defer `AgentEnvelope` until we need async queues, multi-process execution, or
full replay logs.

### Memory Proposal vs Memory Persistence

`StoryMemoryAgent` should produce `MemoryWriteEvent`.

The pipeline or a memory service should perform the actual store operation.

This preserves control over:

- no-write evaluation mode
- offline review
- async memory persistence
- deduplication
- future human-in-the-loop promotion

### Provisional Memory

All online writes are provisional.

Only finalized memory should be used for cross-video retrieval and pattern
extraction by default.

### Tool Trace Size

Do not store full prompts, full raw model responses, or large frame payloads in
`ToolCallRecord`.

Use:

- short summaries
- hashes
- artifact paths

This keeps JSON artifacts readable and prevents report files from becoming too
large.

## 7. Acceptance Criteria

The schema implementation is considered successful when:

- Existing tests still pass.
- New schema and memory policy tests pass.
- `StoryMemoryAgent.process(...)` returns a complete `StoryMemoryResult`.
- The pipeline can run using the new result object.
- The pipeline no longer constructs `CaseMemoryRecord` directly.
- Memory writes are represented as `MemoryWriteEvent`.
- `OFFLINE_EVAL` mode prevents online memory writes.

At that point, the project will have a clean communication layer suitable for
future VLM backend integration and LLM-based story reasoning.
