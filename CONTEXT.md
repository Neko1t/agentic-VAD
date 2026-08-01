# Agentic VAD Experiment Context

This context defines the language used to distinguish reproducible MVP experiment assets from optional legacy reproduction assets.

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
