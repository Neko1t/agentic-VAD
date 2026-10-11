# 开题阶段：视觉单模态最低版运行说明

## 范围与状态

这是独立的视觉预实验配置，不是完整冻结架构实现，也不构成统计显著性声明。

- 感知输入只使用视频画面；VideoLLaMA3 描述 → Llama 3.1 8B 评分。
- OCR、Audio、Memory 关闭；B3 不执行工具选择实验。
- 保留当前标量证据映射和 B2/B4 数学规则，不把它描述成完整结构化事实/直接反证/质量解释器。
- 三组共用同一 caption、同一 Llama 分数、同一标注与帧网格。V0/V1 是评估侧对照，不是三次独立模型运行。
- 本次实现只在本地完成；以下服务器命令需要先部署包含新入口的代码。本文不代表服务器已经同步、模型已经检查或 GPU 实验已经运行。

| 组别 | 分数处理 | 工具 | Memory | 解释 |
|---|---|---|---|---|
| V0 | 原始 Llama 分数，16 帧展开 | NONE | 关闭 | 最低视觉评分基线 |
| V1 | 同一 Llama 分数，逐视频 Gaussian σ=10，然后 16 帧展开 | NONE | 关闭 | 作者式平滑，不是完整复现作者方法 |
| V2 | 同一 Llama 分数，现有标量映射＋B2/B4，无额外 Gaussian | NONE | 关闭 | 时序机制原型 |

资产清单版本 V2 与实验组 V2 是两种不同的命名：前者表示纯视觉文件格式，后者表示时序机制对照组。

## 固定协议

- `ZS-Independent-Offline`；300 帧上下文；16 帧决策步长；配置 2 fps、最多 10 帧；保留尾部短区间。
- 标注区间首尾均包含；池化所有视频帧计算 ROC AUC 与梯形 PR AUC（不是 average precision）。
- 完全正常/完全异常的单视频 AUC 输出 `METRIC_UNDEFINED`，不伪造分数。
- 数据和标注分离：推理只读无标签资产及语义分数；标注只由外层启动器/独立评估命令读取。
- 当前 VLM 后端从原视频内部采样。`sampled_frame_indices`、`sampled_frame_timestamps_us` 是**预处理抽帧记录**，不是 VLM 实际采样轨迹。后者尚未记录；模型配置明确保存 `VIDEO_PATH_PROCESSOR_SAMPLING`。

## 就绪条件与计算资源

需要视频、时序标注、ffmpeg/ffprobe、VideoLLaMA3、Llama 和 caption 派生 embedding 模型。Embedding 为兼容现有证据 DTO 暂时保留，不是另一种感知模态。

| 阶段 | GPU |
|---|---|
| 抽帧、标注清单生成 | 不需要 |
| 视觉 caption/embedding 预计算、Llama 预计算 | 建议已配置好的 4090，顺序运行两个预计算阶段 |
| 已冻结分数上的 B2/B4 推理、帧级评估、V0/V1/V2 比较 | 不需要 |

以下是 Bash 示例。先替换所有路径；不要直接照抄占位符。`VIDEO_DIR` 必须位于 `ASSET_ROOT` 内，源视频不需要音轨。使用新的 bundle、semantic、attempt 和 comparison 名称；不覆盖旧 A/B/C。

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate VAA
cd /root/autodl-tmp/agentic-VAD

ASSET_ROOT=/绝对路径/包含视频的资产目录
VIDEO_DIR="$ASSET_ROOT/videos"
ANNOTATIONS=/绝对路径/Temporal_Anomaly_Annotation_for_Testing_Videos.txt
CAPTION_MODEL=/绝对路径/VideoLLaMA3-7B
EMBEDDING_MODEL=/绝对路径/bge-base-en-v1.5
LLAMA_MODEL=/绝对路径/llama3.1-8b

SOURCE="$ASSET_ROOT/manifests/visual-mini-source.json"
BUNDLE_ROOT=data/agentic_outputs/mvp/precomputed/visual-mini-assets-a
SEMANTIC_ROOT=data/agentic_outputs/mvp/precomputed/visual-mini-semantic-a
INPUT="$BUNDLE_ROOT/mvp_precomputed_input.json"
SEMANTIC="$SEMANTIC_ROOT/mvp_semantic_score_manifest.json"
TARGETS=data/agentic_outputs/mvp/evaluator_inputs/visual-mini-i3-targets-a.json
ATTEMPT=mvp-visual-mini-v2-a
COMPARISON=data/agentic_outputs/mvp/comparisons/visual-mini-a
```

## 1. 纯视觉媒体准备（无需 GPU）

```bash
python -m src.research_mvp.cli prepare-real-media \
  --asset-profile VISUAL_ONLY \
  --video-dir "$VIDEO_DIR" --asset-root "$ASSET_ROOT" \
  --source-manifest "$SOURCE" --dataset-id visual-mini \
  --temporal-protocol ZS-Independent-Offline
```

此模式不探测音轨、不导出 WAV。新 source 为 `MVP_REAL_ASSET_SOURCE_V2`，窗口没有 `audio_ref`。
视觉帧缓存按配置和视频哈希隔离，避免覆盖旧采样结果；仅在源文件、配置、清单和输出哈希都匹配时复用。
一个 source 仍要求所有视频有相同帧率。不要为通过检查偷偷改视频帧率，应先核查或拆分输入。

## 2. 视觉资产预计算（需要模型/GPU）

```bash
python -m src.research_mvp.cli inspect-real-assets \
  --asset-profile VISUAL_ONLY --source-manifest "$SOURCE" --asset-root "$ASSET_ROOT" \
  --caption-model "$CAPTION_MODEL" --embedding-model "$EMBEDDING_MODEL" --gpu-device 0

python -m src.research_mvp.cli precompute-real-assets \
  --asset-profile VISUAL_ONLY --source-manifest "$SOURCE" --asset-root "$ASSET_ROOT" \
  --caption-model "$CAPTION_MODEL" --embedding-model "$EMBEDDING_MODEL" --gpu-device 0 \
  --bundle-id mvp-visual-mini-assets-a --bundle-root "$BUNDLE_ROOT"
```

不要求 OCR/Whisper 路径。清单只登记 CAPTION/EMBEDDING 原始输出及 VLM 证据。
`VISUAL_ONLY` source 与模型配置必须一致；不允许把旧 ALL 清单隐式当成纯视觉清单。

## 3. Llama 评分预计算（需要 GPU）

```bash
python -m src.research_mvp.cli precompute-semantic-scores \
  --input-manifest "$INPUT" --output-root "$SEMANTIC_ROOT" \
  --model-path "$LLAMA_MODEL" --gpu-device 0 --batch-size 32

SEMANTIC_SHA=$(python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$SEMANTIC")
```

沿用原有提示词、采样参数和 eager attention。空 caption、整视频无有效 LLM 分数会失败；部分解析失败沿用既有离线插值，并在报告中披露 `INTERPOLATED` 数量。不能把插值称为真实模型输出，也不能直接外推为因果在线协议。

## 4. 生成评估侧标注（无需 GPU）

```bash
python -m src.research_mvp.evaluator.cli build-frame-targets \
  --source-manifest "$SOURCE" --temporal-annotations "$ANNOTATIONS" \
  --output "$TARGETS" --experiment-config I3
```

每个视频必须有明确标注记录。全正常视频使用正式确认的无异常区间记录，不能把缺失标注静默当成正常。

## 5. 运行时序机制原型并完成正式帧级评估（无需 GPU）

```bash
python -m src.research_mvp.launcher run-asset-smoke \
  --attempt-id "$ATTEMPT" --input-manifest "$INPUT" --target-manifest "$TARGETS" \
  --memory-enabled 0 --tool-policy NONE \
  --semantic-score-manifest "$SEMANTIC" --semantic-score-manifest-sha256 "$SEMANTIC_SHA"
```

纯视觉清单若配 `--tool-policy ALL` 会在创建 attempt 前被拒绝，避免把缺失工具误当成合法调用。
等此命令成功退出后，再运行下一条独立命令；不要与正在执行的推理并发。

## 6. 生成同输入 V0/V1/V2 报告（无需 GPU）

```bash
python -m src.research_mvp.cli compare-visual \
  --project-root . --attempt-id "$ATTEMPT" \
  --input-manifest "$INPUT" --target-manifest "$TARGETS" \
  --semantic-score-manifest "$SEMANTIC" --semantic-score-manifest-sha256 "$SEMANTIC_SHA" \
  --output-root "$COMPARISON"
```

输出目录必须是 `data/agentic_outputs/mvp/comparisons/` 下的新子目录：

- `comparison.json`：完整精度池化/逐视频指标、配置、模型/输入/代码/环境来源。
- `report_zh.md`：中文配置表与结果表，解释边界与正常视频分数摘要。
- `window_scores.jsonl`：caption、LLM 原始响应与解析状态、V0/V1/V2 分数、B2 证据/质量、B4 状态、标注占比、预处理采样信息。
- `receipt.json`：文件哈希、输入哈希和推理/Memory 文件未变校验。

比较器验证输入与模型分数哈希、精确窗口集合、数据集和帧协议、所有窗口 B6 为 `IDENTITY_DISABLED`、工具调用为空，并检查 V2 与正式帧级评估结果完全一致。
也可以复用旧 V1 资产包中的视觉分支，但它必须对应同一个已经完成的 NONE/Memory-off/Llama attempt；报告会标出历史 source 为 ALL，而非伪装成从未执行过多模态预计算。

## 验收与后续边界

2026-10-11 本地验证：research-MVP 184 项全部通过；全仓 290 项通过、4 项既有失败（三项根入口缺失、一项旧管线 GPU 参数）。已通过独立推理/评估进程和比较 CLI 的模拟后端测试。当前本地未找到 ffmpeg/ffprobe，未执行真实解码或 GPU 模型验收；需在 AutoDL 部署后完成，不应将这些单元/集成测试称为新五视频实验结果。

```bash
python -m pytest -q tests/research_mvp
```

先保留五视频历史结果，再用预先固定的正常视频检查高分误报。不要看完结果再挑视频或在同一 mini 上追逐高分。
本阶段不改变 B2/B4 参数、不接入 Memory、不开发复杂 UI。VLM 精确采样轨迹、完整结构化视觉证据解释、分片模型预计算恢复与正式全量统计检验属于后续工作。

模型预计算失败后可以复用已完成的媒体缓存，但 bundle/semantic/推理 attempt 仍要求新目录；不支持覆盖历史 attempt 或原地 resume。
