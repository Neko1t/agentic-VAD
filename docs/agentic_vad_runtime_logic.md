# Agentic VAD Runtime Logic

## 1. Big Picture

The current system works as a layered reasoning pipeline rather than a single
end-to-end model call.

Its runtime idea is:

1. Split a video into short windows.
2. Let `PerceptionAgent` describe each window and assign an initial anomaly
   score.
3. Let `StoryMemoryAgent` combine recent windows into a short story, retrieve
   relevant memory, and calibrate the score.
4. Let `MemoryPolicy` decide whether the current episode is worth storing.
5. Save all intermediate and final artifacts for later inspection.

The full chain is:

```text
Video / Annotation
-> WindowInput
-> PerceptionAgent
-> ObservationCard
-> StoryMemoryAgent
-> StoryMemoryResult
-> MemoryWriteEvent
-> Session / Persistent Memory
-> Reports and JSON artifacts
```

## 2. Entry Point

Main entry:

- `src/pipelines/run_agentic_vad.py`

The pipeline is responsible for orchestration only:

- read annotation rows
- create `VideoRecord`
- split each video into `WindowInput`
- call both agents
- execute memory-write events
- save outputs

It should not implement anomaly reasoning directly and should not build
`CaseMemoryRecord` by hand.

## 3. Video To WindowInput

The pipeline reads annotation rows such as:

```text
video_1.mp4 0 31 1
```

This becomes a `VideoRecord` containing:

- video path
- start frame
- end frame
- label

Then `_build_window_inputs(...)` slices the video into fixed-size windows using
`frame_interval`.

Example:

```text
video_1.mp4
frames 0-31
frame_interval=16
```

becomes:

- `video_1_0000`: frames `0-15`
- `video_1_0001`: frames `16-31`

Each slice becomes a `WindowInput` with:

- `video_id`
- `video_path`
- `window_id`
- `time_span`
- `frame_indices`

## 4. PerceptionAgent Stage

Main file:

- `src/agents/perception_agent.py`

Input:

- one `WindowInput`

Output:

- one `ObservationCard`

This stage is deliberately local. It only answers:

```text
What is happening in this window?
How suspicious does it look right now?
```

It calls four tools:

- `VLMTool.vlm_describe(...)`
- `AudioTool.audio_describe(...)`
- `OCRTool.ocr_extract(...)`
- `ScoreTool.score_observation(...)`

The outputs are normalized into `ObservationCard`, which stores:

- `vision_caption`
- `entities`
- `actions`
- `scene_context`
- `audio_events`
- `ocr_texts`
- `score_raw`
- `score_weighted`
- `uncertainty`
- `reason_trace`
- `tool_trace`

Important boundary:

- `PerceptionAgent` does not do long-range reasoning.
- It does not compare against memory.
- It does not decide the final anomaly verdict.

## 5. Perception Tool Traces

Each tool call is wrapped inside a small tracing layer in `PerceptionAgent`.

Each `ToolCallRecord` may contain:

- `tool_name`
- `input_summary`
- `output_summary`
- `confidence`
- `latency_ms`
- `error`
- `artifact_refs`

If a tool raises an exception:

- the pipeline does not crash
- a fallback result is used
- the exception string is written into `ToolCallRecord.error`

This means the system remains runnable while still preserving debugging
evidence.

## 6. VLMTool Stage

Main file:

- `src/tools/vlm_tool.py`

Current runtime path uses a backend-based design.

Available backends:

- `PrecomputedCaptionBackend`
- `CallableCaptionBackend`
- `MockVLMBackend`
- `NullVLMBackend`

The default pipeline uses:

```python
VLMTool(captions_dir=config.captions_dir)
```

This means the VLM stage currently reads precomputed caption JSON files, not a
real frame-level VLM model.

The tool then derives:

- caption text
- actions
- entities
- scene context
- confidence

The future real `VideoLLaMABackend` is the last major missing model component.

## 7. ScoreTool Stage

Main file:

- `src/tools/score_tool.py`

`ScoreTool.score_observation(...)` performs the first-pass anomaly scoring.

It uses:

- action keywords
- caption keywords
- OCR keywords
- audio keywords
- modality confidence

Outputs:

- `score_raw`
- `score_weighted`
- `modality_weights`
- `reason_trace`
- `uncertainty`

This is still heuristic scoring, but it is deterministic and lightweight, which
makes it a good engineering baseline.

## 8. Recent Buffer And StoryMemoryInput

The pipeline keeps a recent observation buffer:

```python
observations[-rolling_window_size:]
```

This recent slice plus the previous rolling state becomes:

- `StoryMemoryInput`

It contains:

- `video_id`
- `state`
- `recent_observations`
- `top_k`
- `run_mode`

This is the message passed to the second agent.

## 9. StoryMemoryAgent Stage

Main file:

- `src/agents/story_memory_agent.py`

Input:

- `StoryMemoryInput`

Output:

- `StoryMemoryResult`

This stage answers:

```text
What story is emerging across recent windows?
How should memory change the current score?
Should this episode be remembered?
```

The steps are:

1. Update `RollingSummaryState`.
2. Build a story-level text summary.
3. Build a `RetrievalQuery`.
4. Call `RAGTool`.
5. Compute story score.
6. Calibrate local and memory-aware scores.
7. Compute contradiction/disagreement flags.
8. Ask `MemoryPolicy` for a `MemoryWriteEvent`.
9. Return one `StoryMemoryResult`.

## 10. RollingSummaryState

`RollingSummaryState` is the agent's short-lived working memory for the current
video.

It stores:

- `current_scene`
- `active_entities`
- `event_chain`
- `risk_evolution`
- `open_questions`
- `evidence_highlights`

This is not the same as vector memory. It is just the story agent's compact
temporal state.

## 11. RetrievalQuery

After the story text is built, the system constructs a `RetrievalQuery`.

It includes:

- `video_id`
- `action_sequence`
- `evidence_tags`
- `scene_type`
- `story_text`

The query is intentionally more semantic than `ObservationCard`. It is built to
search memory rather than just describe a frame window.

## 12. RAGTool Stage

Main file:

- `src/tools/rag_tool.py`

`RAGTool` merges three memory sources:

1. `CaseMemoryStore`
   finalized persistent cross-video cases
2. `SessionMemoryStore`
   current-video provisional memory from the same run
3. `PatternMemoryStore`
   offline extracted pattern prototypes

The retrieval result becomes `RetrievalResult`, which includes:

- `similar_cases`
- `matched_patterns`
- `retrieval_confidence`

## 13. Session Versus Persistent Memory

There are two important online memory layers:

### SessionMemoryStore

Main file:

- `src/memory/session_store.py`

This store is:

- in-memory only
- scoped by `video_id`
- intended for current-video retrieval

This allows the current video to accumulate provisional context without
polluting cross-video memory.

### CaseMemoryStore

Main file:

- `src/memory/case_store.py`

This store is:

- persistent
- backed by JSONL
- optionally indexed with Chroma

Important rule:

- online writes are `provisional=True`
- default retrieval uses only finalized cases, meaning `provisional=False`

So the system can remember candidate cases online without immediately trusting
them for cross-video retrieval.

## 14. Score Calibration

After retrieval, `StoryMemoryAgent` computes a story score and then calls:

- `ScoreTool.fuse_scores(...)`

This combines:

- local observation score
- story score
- memory-supported score

The result is a `CalibrationResult` with:

- `score_local`
- `score_story`
- `score_memory_adjusted`
- `final_score`
- `calibration_reason`

This is where the second agent can suppress or reinforce the first agent's
judgment.

Typical cases:

- local score high, memory agrees -> final score stays high
- local score high, memory says this is a known normal case -> final score drops
- local score low, but strong temporal or memory evidence exists -> final score
  rises

## 15. MemoryPolicy Stage

Main file:

- `src/memory/policy.py`

This stage decides whether the current episode is memory-worthy.

The output is:

- `MemoryWriteEvent`

Possible decisions:

- `write`
- `skip`
- `update_existing`

Possible case types:

- `high_risk`
- `hard_negative`
- `ambiguous`
- `routine`

Key online rules:

- `offline_eval` mode disables writes
- high-risk episodes can be stored
- hard negatives are valuable and can be stored
- semantic duplicates should not create new vectors
- online writes remain provisional

This design keeps reasoning separate from persistence.

## 16. StoryMemoryResult

The final output of the second agent is `StoryMemoryResult`.

It contains:

- `episode`
- `state`
- `retrieval`
- `calibration`
- `memory_event`
- `disagreement_score`
- `contradiction_flags`
- `tool_trace`

This is the main agent-to-pipeline contract.

## 17. Executing Memory Writes

Back in `run_agentic_vad.py`, the pipeline checks:

```python
if story_result.memory_event.decision == WRITE:
    rag_tool.rag_store_session(case_record)
    rag_tool.rag_store(case_record)
```

So a write event has two destinations:

1. `SessionMemoryStore`
   immediately helps later windows in the same video
2. `CaseMemoryStore`
   persists the case as `provisional=True`

This is the current online memory write path.

## 18. Output Artifacts

At the end of each video, the pipeline writes four artifact groups:

- `observations/{video_id}.json`
- `episodes/{video_id}.json`
- `story_results/{video_id}.json`
- `reports/{video_id}.json`

These have different roles:

- `observations`
  local evidence and first-pass scoring
- `episodes`
  story summaries and memory-adjusted episode-level summaries
- `story_results`
  full second-agent outputs, including retrieval and memory events
- `reports`
  final video-level reporting

This is important because it makes the system inspectable at every stage.

## 19. Offline Promotion Flow

Main files:

- `src/memory/promotion.py`
- `src/pipelines/promote_case_memory.py`

Provisional online cases are not meant to stay provisional forever.

The offline promotion flow does:

1. read provisional cases from `CaseMemoryStore`
2. evaluate them with `MemoryPromotionPolicy`
3. optionally run in `dry_run`
4. promote selected cases to `provisional=False`
5. write a report of promoted, skipped, and missing cases

Once promoted, these cases become part of finalized cross-video retrieval.

## 20. Pattern Extraction Flow

Main file:

- `src/pipelines/extract_patterns_offline.py`

This script reads only finalized cases:

```python
case_store.list_cases(provisional=False)
```

It groups them by:

- label
- action sequence

Then it builds pattern prototypes and stores them in `PatternMemoryStore`.

So the pattern library is always downstream of the finalized case library.

## 21. Evaluation Flow

Main evaluation entry for temporal VAD:

- `src/eval.py`

The original code evaluates temporal anomaly detection at the frame level:

1. load anomaly scores from JSON
2. smooth them with a Gaussian filter
3. repeat clip-level scores to frame-level scores
4. compare against temporal frame annotations
5. compute:
   - ROC AUC
   - PR AUC
   - optimal threshold by Youden's J
   - optimal threshold by max F1

For video anomaly understanding, text generation quality is evaluated in:

- `src/compute_bleu.py`
- `src/gpt_score_eval.py`

For localization, IoU-style localization quality is computed in:

- `src/val_priors.py`

## 22. GPU Memory Safety

The current runtime has low GPU-memory risk because the default path does not
load a real frame-level VLM.

The main future risk point is the planned `VideoLLaMABackend`.

To reduce risk, future real model backends must:

- load heavy models once per backend instance
- run inference under `torch.inference_mode()` or `torch.no_grad()`
- return CPU/Python values only
- never store GPU tensors in schemas, stores, traces, or JSON
- keep traces lightweight
- expose `close()` or `unload()`

## 23. What Is Fully Implemented Versus Still Missing

Implemented:

- agent communication schemas
- perception/stories split
- memory policy
- session memory
- persistent case memory
- offline promotion
- offline pattern extraction
- tiny end-to-end pipeline testing
- tool trace latency/error capture

Still missing:

- a real `VideoLLaMABackend`

So the architecture and engineering workflow are in place, but true frame-level
VLM inference is still the main unfinished model-side component.
