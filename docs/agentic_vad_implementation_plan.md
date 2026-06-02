# Agentic VAD Implementation Blueprint

## Summary
这份计划作为当前线程的规范版持久化方案。

第一版实现目标不是重写整个仓库，而是把现有串行脚本流升级成可编排、可检索、可扩展的研究原型：

- 保留现有 Python + 本地开源模型路线
- 采用原生 Python 编排
- RAG 采用 Chroma 本地持久化
- 先实现 Case Memory + Rolling Summary + Retrieval-Guided Calibration
- Pattern Memory 作为第二阶段离线模块接入

## Tech Stack
### Core Runtime
- Python 3.10
- PyTorch + transformers
- VideoLLaMA3-7B 作为 VLM 首选
- Llama 3.1 8B Instruct 作为文本推理/评分模型首选
- 第一版不引入 LangChain/LlamaIndex

### Data and Interfaces
- Pydantic v2 定义中间数据对象
- Typer 作为新入口 CLI
- 中间产物用 JSON/JSONL
- pandas 用于评估与分析

### Retrieval and Memory
- Chroma 作为本地向量库
- sentence-transformers 作为 embedding 主实现
- JSONL 保留结构化元数据

### Audio and OCR
- faster-whisper 作为 ASR 首选
- easyocr 作为 OCR 首选
- 第一版允许音频/OCR 作为可选 tool

### Engineering
- pytest
- logging
- rich 可选

## Implementation Changes
### Directory Layout
- `src/core`
- `src/tools`
- `src/agents`
- `src/memory`
- `src/pipelines`
- `src/eval`

### Core Schemas
- `ObservationCard`
- `RollingSummaryState`
- `EpisodeSummary`
- `DecisionReport`
- `CaseMemoryRecord`
- `PatternMemoryRecord`

### Tool Contracts
- `vlm_describe(window_input)`
- `audio_describe(audio_chunk)`
- `ocr_extract(window_frames)`
- `score_observation(observation_card)`
- `update_rolling_summary(state, new_cards)`
- `summarize_episode(state, recent_cards)`
- `rag_retrieve(query_struct, top_k)`
- `rag_store(case_record)`
- `fuse_scores(local, story, memory)`

### Phase Plan
1. Tool adapter + schema/config
2. Perception Agent + ObservationCard + weighted scoring
3. Story-Memory Agent + Rolling Summary + Case Memory
4. Retrieval-Guided Calibration + DecisionReport
5. Offline Pattern Extractor

## Notes
- 主流程保持离线研究原型定位
- Chroma 负责向量检索，JSONL 负责结构化元数据
- Pattern Memory 不是首发阻塞项
