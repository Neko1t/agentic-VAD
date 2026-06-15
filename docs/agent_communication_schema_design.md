# Agent Communication Schema Design

## 1. Design Principles

Agent communication schemas should act as stable contracts between modules.
They should be explicit enough for debugging and replay, but not so heavy that
the current research pipeline becomes hard to iterate on.

Recommended principles:

- Keep perception local. `ObservationCard` should describe one video window and
  its local evidence only.
- Keep story reasoning separate. Long-range interpretation belongs to
  `StoryMemoryAgent`, not `PerceptionAgent`.
- Treat tool calls as evidence. Important tool invocations should be captured in
  trace records.
- Separate memory proposal from memory persistence. An agent may propose a memory
  write, but a store or orchestrator performs the actual write.
- Preserve replayability. The communication payload should be serializable to
  JSON/JSONL without custom objects.

## 2. Recommended Communication Flow

```text
WindowInput
  -> PerceptionAgent
  -> ObservationCard
  -> StoryMemoryAgent
  -> StoryMemoryResult
  -> Pipeline / Memory Service
  -> DecisionReport + Memory Artifacts
```

The pipeline should pass structured objects between agents. It should avoid
passing raw captions, raw model responses, or partially parsed dictionaries
outside tool adapters.

## 3. Shared Metadata Schemas

### AgentEnvelope

Use an optional envelope when the system needs message-level metadata,
replayability, or async execution later.

```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class AgentEnvelope(BaseModel):
    message_id: str
    source_agent: str
    target_agent: str | None = None
    message_type: str
    created_at: datetime
    video_id: str | None = None
    window_id: str | None = None
    payload_schema: str
    payload: dict[str, Any]
```

For the first implementation, direct Pydantic objects are enough. The envelope
can be introduced when async queues, agent replay, or multi-process execution
becomes necessary.

### ToolCallRecord

Tool traces are useful for debugging score changes and building experiment
audit logs.

```python
class ToolCallRecord(BaseModel):
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    error: str | None = None
```

Recommended usage:

- `ObservationCard.tool_trace` records VLM/audio/OCR/scoring calls.
- `StoryMemoryResult.tool_trace` records retrieval and calibration calls.

## 4. Perception Agent Output

The existing `ObservationCard` is already close to the desired contract. The
next version should keep it local and avoid story-level interpretation.

```python
class ObservationCard(BaseModel):
    video_id: str
    window_id: str
    time_span: TimeSpan

    # Local perception facts
    vision_caption: str = ""
    entities: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    scene_context: str = ""
    audio_events: list[str] = Field(default_factory=list)
    ocr_texts: list[str] = Field(default_factory=list)

    # Perception quality and local scoring
    modality_confidence: ModalityConfidence = Field(default_factory=ModalityConfidence)
    score_raw: float = Field(default=0.0, ge=0.0, le=10.0)
    score_weighted: float = Field(default=0.0, ge=0.0, le=10.0)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_trace: list[str] = Field(default_factory=list)

    # Optional audit trace
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
```

Important boundary:

- Allowed: visible entities, observed actions, local caption, local score.
- Not allowed: final abnormal decision, long-term causal story, RAG memory
  conclusion, cross-video comparison.

## 5. Story-Memory Agent Input

`StoryMemoryAgent` should consume a bounded batch of recent observations plus
the previous rolling state.

```python
class StoryMemoryInput(BaseModel):
    video_id: str
    state: RollingSummaryState
    recent_observations: list[ObservationCard]
    top_k: int = Field(default=5, ge=1)
```

This input model is optional but recommended. It makes tests and future async
execution easier because one object contains the full story-agent request.

## 6. Story-Memory Agent Output

`StoryMemoryResult` should be the main output contract from the second agent.

```python
class StoryMemoryResult(BaseModel):
    video_id: str
    episode: EpisodeSummary
    state: RollingSummaryState
    retrieval: RetrievalResult
    calibration: CalibrationResult
    memory_event: MemoryWriteEvent | None = None
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
```

This avoids returning loose tuples such as `(episode, state)` and makes the
agent's full reasoning result inspectable.

## 7. CalibrationResult

The existing `CalibrationResult` is a good base. Keep both intermediate and
final scores.

```python
class CalibrationResult(BaseModel):
    score_local: float = Field(ge=0.0, le=10.0)
    score_story: float = Field(ge=0.0, le=10.0)
    score_memory_adjusted: float = Field(ge=0.0, le=10.0)
    final_score: float = Field(ge=0.0, le=10.0)
    calibration_reason: list[str] = Field(default_factory=list)
```

Why keep all scores:

- `score_local` shows what perception believed.
- `score_story` shows temporal-context risk.
- `score_memory_adjusted` shows memory influence.
- `final_score` is the decision-facing risk.

This is especially important for hard negatives: local evidence may be scary,
but context or memory can suppress the final score.

## 8. Memory Write Event

Memory writing should be expressed as an event, not a side effect hidden inside
summary generation.

```python
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
    case_record: CaseMemoryRecord | None = None
    duplicate_of: str | None = None
    similarity_to_existing: float | None = Field(default=None, ge=0.0, le=1.0)
```

Recommended semantics:

- `WRITE`: insert a new case record.
- `SKIP`: do not write because the segment is low value, too uncertain, or
  duplicated.
- `UPDATE_EXISTING`: do not add another vector; update metadata such as
  `hit_count` if supported later.

## 9. Case Memory Record Extensions

The current `CaseMemoryRecord` already works. For stronger memory policy, add
these optional fields later:

```python
class CaseMemoryRecord(BaseModel):
    ...
    case_type: MemoryCaseType = MemoryCaseType.AMBIGUOUS
    source: str = "online_inference"
    provisional: bool = True
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    local_score: float | None = Field(default=None, ge=0.0, le=10.0)
    final_score: float | None = Field(default=None, ge=0.0, le=10.0)
    retrieval_case_ids: list[str] = Field(default_factory=list)
    matched_pattern_ids: list[str] = Field(default_factory=list)
    hit_count: int = Field(default=1, ge=1)
```

These fields help distinguish true positives, hard negatives, ambiguous cases,
and routine duplicated segments.

## 10. MemoryPolicy Interface

`MemoryPolicy` should consume the full story-memory result context and return a
memory event.

```python
class MemoryPolicy:
    def decide(
        self,
        episode: EpisodeSummary,
        state: RollingSummaryState,
        calibration: CalibrationResult,
        observations: list[ObservationCard],
        retrieval: RetrievalResult,
    ) -> MemoryWriteEvent:
        ...
```

Suggested gating rules:

1. High-risk positive:
   - `final_score >= 8.0`
   - average or latest `uncertainty <= 0.3`
   - write `case_type=HIGH_RISK`

2. Hard negative:
   - `score_local >= 7.0`
   - `final_score <= 3.0`
   - write `case_type=HARD_NEGATIVE`

3. Ambiguous but informative:
   - `5.0 <= final_score < 8.0`
   - high disagreement between local score and memory-adjusted score
   - write as provisional only if not duplicated

4. Semantic duplicate:
   - nearest similar case similarity `>= 0.95`
   - skip or update existing case instead of adding a new vector

5. Online inference isolation:
   - all online writes are `provisional=True`
   - finalized promotion happens offline only

## 11. Recommended First Code Change

Add the following to `src/core/schemas.py`:

- `ToolCallRecord`
- `StoryMemoryInput`
- `StoryMemoryResult`
- `MemoryWriteDecision`
- `MemoryCaseType`
- `MemoryWriteEvent`

Then add:

- `src/memory/policy.py`

Finally refactor:

- `StoryMemoryAgent.summarize_episode(...)` can remain for compatibility.
- Add `StoryMemoryAgent.process(...)` returning `StoryMemoryResult`.
- Move pipeline `_build_case_record(...)` logic into `MemoryPolicy`.

This gives the project a clean agent communication layer without forcing a big
rewrite.
