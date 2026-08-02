# Freeze LLM semantic scores before MVP inference

The LLM scores the current frozen caption windows in a label-free precomputation step, and MVP inference consumes a verified Semantic Score Manifest without loading the LLM. A score `s` maps into B2 as `direction = sign(s - 0.5)` and `q_in = abs(2s - 1)`, so the resulting evidence is exactly `2s - 1`; `s = 0.5` is neutral. This preserves continuous ranking, avoids a new threshold parameter, and keeps expensive model execution outside the evaluator and deterministic inference worker.
