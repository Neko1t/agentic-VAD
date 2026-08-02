# Agentic VAD Experiment Context

This context defines the language used to distinguish reproducible MVP experiment assets from optional legacy reproduction assets and to explain experiment behavior without contaminating inference with evaluator knowledge.

## Language

**Real-Asset MVP Model Set**:
The four local model resources required by real-asset MVP precomputation: VideoLLaMA3, EasyOCR English, faster-whisper-small, and bge-base-en-v1.5.
_Avoid_: all models, models-all, baseline models

**Legacy Baseline Model**:
A model used to reproduce the original scoring pipeline but not consumed by the real-asset MVP path. Llama 3.1 8B is currently in this category.
_Avoid_: MVP model, required model

**Asset Ready**:
A local asset state whose required files are complete and whose integrity checks have succeeded. Directory presence or a partial download is not Asset Ready.
_Avoid_: downloaded, present, probably complete

**Decision Interval**:
The non-overlapping original-frame span that owns one anomaly prediction. The final interval may contain fewer frames than the configured stride.
_Avoid_: evidence window, clip

**Evidence Context**:
The bounded media span inspected to produce evidence for one Decision Interval. It may be centered for offline protocols or trailing for causal protocols, and it does not define prediction cadence.
_Avoid_: decision window, score interval

**Prediction Grid**:
The ordered sequence of Decision Intervals covering a video exactly once at a fixed frame stride.
_Avoid_: sampled frames, overlapping windows

**Frame Prediction**:
The anomaly score assigned to one original video frame by projecting its Decision Interval prediction onto that frame.
_Avoid_: window target, clip sample

**Temporal Protocol**:
The registered policy that fixes Prediction Grid cadence, Evidence Context direction, and evaluator postprocessing for an experiment configuration.
_Avoid_: window size, preprocessing preset

**Accepted Evidence**:
Evidence whose artifact identity and protocol contract were validated. Acceptance says nothing about semantic value or score impact.
_Avoid_: Useful evidence, contributing evidence

**Informative Evidence**:
Accepted evidence that contains non-neutral semantic support or opposition relevant to anomaly interpretation.
_Avoid_: Accepted evidence, non-empty evidence

**Contributed Evidence**:
Accepted evidence that numerically changed a downstream experiment score. Contribution does not imply that the change was correct or beneficial.
_Avoid_: Informative evidence, helpful evidence

**Inference Diagnostic**:
An immutable, label-free account of the decision inputs, evidence states, score changes, and lineage for one accepted inference window.
_Avoid_: Evaluation trace, reasoning transcript

**Evaluator Diagnostic Report**:
A post-freeze report that joins inference diagnostics with evaluator targets to compare stage behavior against formal outcomes.
_Avoid_: Inference diagnostic, training signal
