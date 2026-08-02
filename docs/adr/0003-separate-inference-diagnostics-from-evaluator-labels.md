# Separate inference diagnostics from evaluator labels

Inference diagnostics are mandatory immutable artifacts bound into the inference freeze, but they contain only structured decision evidence and no evaluator targets. Targets are joined with frozen diagnostics only in the separate evaluator process, which preserves zero-shot isolation while still allowing stage-by-stage failure attribution; changing B3 thresholds or adding LLM scoring remains a separate experiment configuration rather than an instrumentation side effect.
