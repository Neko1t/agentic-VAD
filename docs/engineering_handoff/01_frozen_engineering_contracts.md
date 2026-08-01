# Multiagents Training-Free Agentic VAD 冻结工程契约

> 文档编号：`TFAVAD-ENG-01`  
> 契约版本：`tfavad.contract/1.0.0`  
> Schema 版本：`tfavad.schema/1.0.0`  
> 协议版本：`tfavad.protocol/1.0.0`  
> 状态：工程实现基线，规范性  
> 理论基线：`docs/achieved/training_free_agentic_vad_evolution.md`  
> 配套文档：`02_reference_algorithms.md`、`03_contract_test_matrix.md`、`04_theory_to_code_gap_analysis.md`

## 1. 目的、边界与规范词

### 1.1 目的

本文冻结工程师必须实现和验收的外部可观察契约，包括：

- 运行协议、数据可见性与推理/评估隔离；
- 公共 Schema、字段语义、数值域、时间与标识规则；
- Agent 角色、读写权限、状态所有权和合法消息顺序；
- 每窗口最多两次观察 pass、B4 exactly-once 提交和 predict-before-write；
- 事件日志、版本快照、重放、CAS、失败与回退语义；
- 确定性、来源记录、稳定 artifact 路径和最低验收条件。

本文不冻结内部类名、包结构、文件拆分、进程拓扑、数据库产品、向量索引实现、局部缓存和不改变可观察行为的性能优化。工程师可以自由设计这些内容，但不得改变本文契约。

### 1.2 规范词

- **MUST / 必须**：实现不满足即为契约失败。
- **MUST NOT / 禁止**：出现即为协议违规。
- **SHOULD / 应当**：除非有记录充分的工程原因，否则必须满足；偏离不得改变数值或因果语义。
- **MAY / 可以**：可选实现，不得成为其他 MUST 条款成立的前提。

正文中的公式、字段约束、状态机表和失败处置具有同等规范性。示例路径中的占位符使用尖括号表示，不是字面目录名。

### 1.3 适用范围

| 理论块 | 工程范围 | 本文冻结内容 |
|---|---|---|
| B0 | 包含 | 三种协议、标签隔离、predict-before-write |
| B1 | 包含 | Visual/Audio 来源族、工具适配器质量和缺失语义 |
| B2 | 包含 | 结构化证据、时间对齐、来源族融合和本地证据输出 |
| B3 | 包含 | Evidence-Gap Controller、预算、两次 pass 上限 |
| B4 | 包含 | Sticky Temporal Belief、Elastic Dual Clock、状态机 |
| B5 | 包含 | Episode、Candidate、Reservoir、检索防火墙和 Memory 生命周期 |
| B6 | 包含 | 有界 Memory 建议、选择性再观察、唯一提交 |
| B7 | 排除 | 自适应时间采样不得出现在主线实现或主结果中 |
| B8 | 包含 | 角色权限、消息、重放、双钥匙写入和 CAS |
| B9 | 包含 | 实验配置、freeze manifest、稳定产物和验收入口 |

### 1.4 需求优先级

发生冲突时按以下优先级处理：

1. B0 的 training-free、zero-shot、因果可见性和 ground-truth 隔离；
2. B8 的权限、不可变消息、exactly-once 和 predict-before-write；
3. B2/B3/B4/B5/B6 的冻结数学不变量和算法顺序；
4. B9 的实验身份、资源、报告和 artifact 约束；
5. 本文给出的工程表示细节；
6. 现有原型行为。

现有原型与 1-5 冲突时，原型必须通过显式 Legacy Adapter 迁移，禁止把原型行为解释为 Schema v1。

## 2. 全局不可违反不变量

任一正式运行必须同时满足下列不变量：

1. 所有模型参数、Prompt、工具注册表、质量算法、预算、数学公式和主超参数在首次目标预测前冻结。
2. Inference 进程和配置无法读取 annotation、ground truth、目标指标或未来不允许信息。
3. `ZS-Independent-*` 每个视频从空跨视频 Memory 开始；`ZS-Stream-Causal` 整条流只在最开始从空 Memory 开始。
4. Causal 窗口只能读取当前与过去窗口；Stream 视频只能读取排序更早且已完成预测冻结的视频案例。
5. 当前视频的跨视频案例写入发生在全部窗口预测持久化并冻结之后。
6. 缺失、失败、不可用、空但合法均不等于正常证据。
7. 每个通道、每个目标窗口最多产生一个 `ModalityEvidence`；每个目标窗口最多接受一个 `B4Decision`。
8. B5 排名只能读取 observation-only `RetrievalKey`；`AdvisoryPayload` 只能在 ordered top-k manifest 持久化后解锁。
9. Memory 建议不能成为新的 observed fact，也不能改变 B2 本地记录或 B4 物理时钟。
10. 每窗口只允许 `pass_id=0` 和可选的 `pass_id=1`；不得产生第三个 pass。
11. Hysteresis 不得回写或修改连续分数 `z_t`。
12. 主线质量估计不可得时 fail closed；禁止默认 `Q_in=1` 或 `Q_src=1`。
13. 所有持久化状态变化可由 append-only events 和版本快照重放。
14. 数据库、向量索引和缓存均为可重建派生状态，不是唯一事实来源。
15. B7 关闭，B4 后不再施加 Gaussian smoothing。

## 3. 协议与配置隔离

### 3.1 协议枚举

`protocol` 必须是以下精确枚举之一：

```text
ZS_INDEPENDENT_OFFLINE
ZS_INDEPENDENT_CAUSAL
ZS_STREAM_CAUSAL
```

| 协议 | 当前完整视频 | 未来窗口 | Session Case | 跨视频 Memory | 视频结束行为 |
|---|---:|---:|---:|---:|---|
| `ZS_INDEPENDENT_OFFLINE` | 可读 | 可用于已声明的离线推理，但 B4 主线仍按窗口前向提交 | 可用 | 禁止 | 清空 Session/Long-Term 可变状态 |
| `ZS_INDEPENDENT_CAUSAL` | 不可预读 | 禁止 | 仅已关闭的过去 Episode | 禁止 | 清空 Session/Long-Term 可变状态 |
| `ZS_STREAM_CAUSAL` | 不可预读 | 禁止 | 仅已关闭的过去 Episode | 仅更早已冻结视频 | 保留获准 Long-Term Memory |

三种协议必须产生不同的 `protocol` 值和不同结果分栏。禁止将它们合并成同一独立零样本结果。

### 3.2 Entry 类型

`entry_type` 必须是：

```text
RAW
CAPTION
SCORE
FROZEN_B2
FROZEN_SCORE
```

- `RAW`/`CAPTION` 可以支持完整系统、B2 和 B3 贡献声明。
- `SCORE`/`FROZEN_SCORE` 只支持时序、Memory 和决策机制实验，必须绕过 B1/B2/B3 工具获取。
- `FROZEN_B2` 必须绑定完全相同的 B2 artifact manifest hash，才可用于 B4/B5/B6 配对消融。
- 任何预计算输入必须记录生成模型、模型哈希、Prompt、解码配置、采样配置和文件哈希。

### 3.3 物理配置隔离

推理和评估必须使用两个独立根配置：

```text
InferenceConfigV1
EvaluatorConfigV1
```

`InferenceConfigV1` 及其传递依赖中禁止出现以下字段或等价别名：

```text
annotation_path
ground_truth_path
label_path
class_list_from_dataset
metric_result_path
```

`EvaluatorConfigV1` 必须只在 `PredictionFreezeRecord`、所有预测文件和当前 run 的 Memory events 冻结后打开。Evaluator 只能写 `evaluation/`、`metrics/`、`bootstrap/` 和 `comparison_tables/`，禁止写回 inference、prediction 或 memory 目录。

### 3.4 InferenceConfigV1

| 字段 | 类型 | 必需 | 约束 |
|---|---|---:|---|
| `schema_version` | string | 是 | 精确等于 `tfavad.schema/1.0.0` |
| `protocol_version` | string | 是 | 精确等于 `tfavad.protocol/1.0.0` |
| `experiment_id` | string | 是 | B9 冻结 ID 或预注册扩展 ID |
| `protocol` | enum | 是 | 3.1 枚举 |
| `entry_type` | enum | 是 | 3.2 枚举 |
| `dataset_id` | string | 是 | 不含单视频标签语义 |
| `input_manifest_ref` | ArtifactRef | 是 | 输入 manifest 及 SHA-256 |
| `freeze_manifest_ref` | ArtifactRef | 是 | 只读 freeze manifest |
| `tool_registry_ref` | ArtifactRef | 条件 | RAW/CAPTION 主线必需 |
| `b3_cost_table_ref` | ArtifactRef | 条件 | 启用 B3 时必需 |
| `sampling_config` | object | 是 | 窗口和步长均使用整数微秒 |
| `budgets` | object | 是 | 正整数预算；策略在运行中不可自调 |
| `memory_config` | object | 是 | scope、K、k_ret、B_ret、RRF、seed |
| `determinism_config` | object | 是 | seed、后端确定性声明、容差 |
| `output_root` | string | 是 | 必须在 `data/agentic_outputs/` 下 |
| `memory_root` | string | 是 | 必须在 `data/agentic_memory/` 下 |

正式主 Memory 设置必须为 `K=512`、`k_ret=5`、`B_ret=15`、`c_RRF=60`、`reservoir_seed=0`。其他值必须具有不同 experiment/config identity，且标记为 sensitivity，不得回填主设置。

### 3.5 EvaluatorConfigV1

| 字段 | 类型 | 必需 | 约束 |
|---|---|---:|---|
| `schema_version` | string | 是 | 精确版本匹配 |
| `run_id` | Id | 是 | 指向已经冻结的 run |
| `prediction_freeze_ref` | ArtifactRef | 是 | 哈希必须验证通过 |
| `annotation_manifest_ref` | ArtifactRef | 是 | 仅 Evaluator 可读 |
| `metric_definition_ref` | ArtifactRef | 是 | 与 freeze manifest 一致 |
| `bootstrap_config` | object | 是 | 主设置 video-level、10000、seed 0、95% |
| `output_root` | string | 是 | run root；Evaluator 只能写 `evaluation/`、`metrics/`、`bootstrap/`、`comparison_tables/` allowlist |

## 4. 角色、权限与状态所有权

### 4.1 角色权限矩阵

`R` 表示可读，`W` 表示唯一可写所有者，`-` 表示禁止访问。

| 数据/操作 | Controller | Evidence | Memory | Decision | Orchestrator | Evaluator |
|---|---:|---:|---:|---:|---:|---:|
| 无标签 WindowInput | R | R | - | - | W | - |
| 预检形态 `Xi_t` | R | W | - | - | R | - |
| ToolPlan / budget debit | W | R | - | - | R/验证 | - |
| Tool raw output / EvidencePacket | - | W | - | - | R/持久化 | - |
| B2Output | R/受限 | W | R/事实键 | R | R/持久化 | - |
| RetrievalKey / ranking trace | - | - | W | - | R/持久化 | - |
| AdvisoryPayload | - | - | W | R/manifest 后 | R/哈希验证 | - |
| EvidenceRequest | R | - | - | W | R/路由 | - |
| B6DecisionEvidence / B6Trace | - | - | - | W | R/持久化 | - |
| B4 state / B4Decision | - | - | - | W | R/提交控制 | - |
| Session Case 发布 | - | - | W | - | R/顺序验证 | - |
| Candidate / Reservoir | - | - | W | - | R/许可与 CAS | - |
| PredictionFreezeRecord | - | - | R | W | R/验证冻结 | - |
| WritePermit | - | R/禁止 | R | R/禁止 | W | - |
| Ground truth / metrics | - | - | - | - | - | W |

受限读取的含义：Controller 只能读取字段覆盖、冲突 atom ID、工具状态和无方向 `EvidenceRequest`，禁止读取 `d_t`、Memory 方向、B4 状态、`z_t` 或指标。

### 4.2 数值状态所有权

| 状态/数值 | 唯一所有者 | 其他模块约束 |
|---|---|---|
| `Q_in/Q_src/r_j` | Evidence/B1 adapter | Controller 只看可用性；Memory 不得修改 |
| `q_t/d_t/kappa_t/e_local/u_local` | Evidence/B2 | B6 只读；不得覆盖原记录 |
| `ToolPlan`、预算余量 | Controller/B3 | Orchestrator 只验证和持久化 |
| 检索排名、top-k、case lifecycle、memory version | Memory/B5 | Decision 不能选择或重排案例 |
| `e_commit/reliability_commit/d_commit/u_commit` | Decision/B6 | Memory 不得产生最终提交值 |
| `F/S/M/U/z/state` 与物理时钟 | Decision/B4 | B6/Memory 不得推进时钟 |
| stream order、message/event commit order、permit | Orchestrator | 不得计算风险或改写数学输出 |
| 标签和全部评估量 | Independent Evaluator | 运行 Agent 永不可读 |

### 4.3 部署自由与能力隔离

所有角色可以位于同一 Python 进程，也可以拆成服务。无论部署方式如何，消息 Schema、权限检查、不可变 payload、hash binding 和状态所有权必须保持一致。直接函数调用不能成为绕过权限或事件记录的后门。

## 5. 公共类型、时间、数值、ID 与哈希

### 5.1 JSON 类型约束

- 所有公共消息和规范 artifact 必须是 JSON/JSONL 可表达数据。
- 数值仅允许有符号 64 位整数或有限 IEEE-754 binary64；禁止 `NaN`、`Infinity` 和 `-Infinity`。
- 布尔值不得用 `0/1` 替代；缺失值不得用空字符串替代。
- 未知、缺失、失败必须使用明确 enum/status；`null` 只用于 Schema 明确允许的字段。
- 集合在 JSON 中表示为去重数组，并按本文规定的 canonical order 排序。

### 5.2 规范时间

规范物理时间类型为：

```text
TimeIntervalV1 = {
    start_us: int64,
    end_us: int64,
    start_frame: int64 | null,
    end_frame_exclusive: int64 | null,
    fps_num: int64 | null,
    fps_den: int64 | null
}
```

必须满足：

```text
0 <= start_us < end_us
duration_us = end_us - start_us
interval = [start_us, end_us)
```

- 整数微秒是唯一规范时间；帧号只是辅助兼容字段。
- 帧区间同样为左闭右开 `[start_frame,end_frame_exclusive)`。
- 出现任一帧字段时，四个帧/FPS 字段必须全部出现，`fps_num>0`、`fps_den>0`。
- 帧时间转换只能使用 manifest 冻结的有理 FPS 和统一舍入规则；转换误差必须记录，禁止用帧号覆盖已经给出的微秒时间。
- 区间相交、覆盖、时长权重、因果顺序和 B4 `delta_t` 均以微秒字段计算。
- 同一视频窗口按 `(start_us,end_us,window_ordinal)` 严格全序；相同规范区间的重复窗口必须被去重或判为配置错误。

### 5.3 标量域

| 类型名 | 数值域 | 语义 |
|---|---|---|
| `UnitScalar` | `[0,1]` | 质量、可靠度、冲突、覆盖、权重 |
| `SignedScalar` | `[-1,1]` | 正负方向或有界证据 |
| `RiskRankingScore` | `[0,1]` | 排序信念，不是校准概率 |
| `PositiveCost` | 正 int64 | B3 冻结预算单位 |
| `MemoryVersion` | 非负 int64 | 每次成功跨视频事务严格加一 |

所有边界比较使用：

```text
abs_tol = 1e-12
rel_tol = 1e-9
tol(x,y) = max(abs_tol, rel_tol * max(abs(x),abs(y)))
```

`x` 只有在 `x-y > tol(x,y)` 时才视为严格大于 `y`；差值落入容差带时视为相等并使用冻结 tie-break。该规则用于状态转换、排序并列和验收，避免数值等价后端在自然边界产生不同结构结果。不得使用容差把越界值静默 clip 回合法域；超过容差的越界必须拒绝。

### 5.4 Canonical JSON 与哈希

规范 hash 算法固定为 SHA-256，输出 64 位小写十六进制。哈希输入必须先 canonicalize：

1. UTF-8 编码，无 BOM；
2. object key 按 Unicode code point 升序；
3. array 保持有语义的顺序；集合数组在进入 canonicalizer 前按各自规则排序；
4. 字符串保持原值，不做基于 locale 的大小写或 Unicode 隐式变换；文本规范化必须由上游显式版本化；
5. 整数使用最短十进制；binary64 使用确定性最短 round-trip 十进制；`-0.0` 规范化为 `0`；
6. 禁止无意义空白；布尔与 null 使用 JSON 小写字面值。

```text
payload_hash = SHA256(canonical_json(payload))
artifact_hash = SHA256(file_bytes)
```

实现可以采用经过验证的 RFC 8785/JCS 等价实现，但输出必须通过项目 canonical hash test vectors。禁止依赖语言默认 dict 顺序、locale 或平台浮点格式。

任何对象若包含自己的 `*_id` 或 `*_hash` 字段，计算该自标识值时必须从 hash 输入中省略该字段；其他父 ID/hash 仍保留。计算后填入自标识字段，再由父 artifact 对完整对象做外层文件哈希。禁止把尚未计算的空字符串、null 或旧 hash 混入自哈希输入。

### 5.5 ID 规则

所有 ID 都是 opaque string，不得包含异常类别、正常/异常标签或可从文件名推断的类别语义。

| ID | 规范构造 |
|---|---|
| `run_id` | `run_` + SHA256(freeze manifest hash、experiment_id、repeat_id、order manifest hash) |
| `video_id` | `vid_` + SHA256(dataset namespace、无类别逻辑资源键) |
| `window_id` | `win_` + SHA256(run_id、video_id、window_ordinal、TimeIntervalV1) |
| `atom_id` | `atm_` + SHA256(EvidenceAtom 去除 atom_id 后的 canonical payload) |
| `candidate_id` | `cand_` + SHA256(video_id、episode interval、role、source atom IDs) |
| `case_id` | `case_` + SHA256(immutable EpisodicCase core) |
| `permit_id` | `permit_` + 第 10.4 节冻结字段哈希 |
| `event_id` | `evt_` + SHA256(event stream、idempotency key、payload hash、parent IDs) |
| `snapshot_id` | `snap_` + SHA256(snapshot canonical payload) |

原始文件路径可以进入受控 provenance，但不能作为公共 ID。相同逻辑输入在同一 freeze manifest 下必须产生相同结构 ID。

### 5.6 ArtifactRef 与版本集合

```text
ArtifactRefV1 = {
    uri: string,
    sha256: string,
    media_type: string,
    byte_length: int64,
    producer_message_id: string | null
}

VersionSetV1 = {
    models: [{id, version, sha256}],
    tools: [{id, version, config_hash}],
    prompts: [{id, version, sha256}],
    tokenizers: [{id, version, sha256}],
    algorithms: [{id, version, config_hash}]
}
```

`uri` 必须是 run root 或明确 memory namespace 可解析的相对 URI；禁止仅保存不可移植的临时绝对路径。数组按 `id`、`version`、hash 排序。

## 6. Schema v1 公共消息

### 6.1 MessageEnvelopeV1

所有 Agent 间消息必须封装为：

```text
MessageEnvelopeV1<T> = {
    schema_version: string,
    protocol_version: string,
    message_id: string,
    run_id: string,
    video_id: string,
    window_id: string | null,
    pass_id: 0 | 1 | null,
    producer: enum,
    payload_schema: string,
    payload_type: string,
    parent_message_ids: [string],
    causal_time: CausalTimeV1,
    versions: VersionSetV1,
    input_hash: string,
    payload_hash: string,
    created_at_utc: string,
    payload: T
}
```

`producer` 精确枚举：

```text
ORCHESTRATOR
CONTROLLER
EVIDENCE
MEMORY
DECISION
```

Evaluator 不产生运行时 MessageEnvelope。

```text
CausalTimeV1 = {
    stream_position: int64 | null,
    window_ordinal: int64 | null,
    phase_ordinal: int64
}
```

- `created_at_utc` 采用 RFC 3339 UTC，仅供审计，禁止参与算法和排序。
- `parent_message_ids` 去重并按消息的逻辑因果顺序排列；并发同层父消息按 message ID 排序。
- `input_hash` 是消费者实际读取的全部父 payload hash、config hash 和 artifact hash 的规范清单哈希。
- `payload_schema` 是稳定基础类型，如 `ToolPlanV1`；`payload_type` 是逻辑消息槽，如 `ToolPlanV1:step-000`。
- 窗口级消息 `pass_id` 必须是 0 或 1；视频级 `PredictionFreezeRecord`、`WritePermit`、`MemoryWriteEvent` 的 `window_id` 与 `pass_id` 必须同时为 null。
- 重复步骤使用不同 slot。这样理论幂等键仍为：

```text
K_msg = (
  run_id, video_id, window_id,
  pass_id, producer, payload_type
)
```

- 每 pass 仅一次的最终对象使用 `:final`；第 `n` 个自适应动作使用 `:step-NNN`，NNN 从 000 连续递增。
- 同一 `K_msg` 与相同 payload hash 为重复重放，必须幂等忽略；同一 `K_msg` 与不同 payload hash 为 `CONFLICTING_REPLAY`。
- `message_id` 必须按 B8 公式，由 protocol version、`K_msg`、父 ID、input hash 和 payload hash 计算。
- 消费者禁止原地修改 envelope 或 payload。

### 6.2 WindowInputV1

```text
WindowInputV1 = {
    video_id: string,
    window_id: string,
    window_ordinal: int64,
    interval: TimeIntervalV1,
    delta_us: int64,
    entry_type: enum,
    media_refs: [ArtifactRefV1],
    precomputed_refs: [ArtifactRefV1],
    availability: {
        video: enum,
        audio: enum,
        speech: enum,
        visible_text: enum,
        motion: enum
    },
    source_manifest_hash: string
}
```

`availability` 枚举为 `AVAILABLE | UNAVAILABLE | UNKNOWN | NOT_APPLICABLE`。它只描述信息形态，禁止包含风险方向。`delta_us>0`；首窗口使用其规范步长或 manifest 明确的首间隔规则。

### 6.3 PreflightObservationV1

```text
PreflightObservationV1 = {
    window_id: string,
    has_audio_track: boolean | null,
    voice_activity: enum,
    text_region_activity: enum,
    motion_computable: boolean | null,
    unreadable_field_refs: [string],
    activated_optional_fields: [enum],
    algorithm_versions: VersionSetV1
}
```

活动 enum 为 `PRESENT | ABSENT | UNKNOWN | NOT_APPLICABLE`。该对象只能激活 B3 需求，禁止出现 anomaly、normal、风险类别或方向分数。

### 6.4 ToolActionV1 与 ToolPlanV1

```text
ToolActionV1 = {
    tool_id: string,
    adapter_mode: string,
    action_key: string,
    capability_fields: [enum],
    fixed_cost: int64,
    frozen_order: int64
}

GapSnapshotV1 = {
    activated_requirements: [enum],
    covered_fields: [enum],
    missing_fields: [enum],
    conflict_fields: [enum],
    requested_fields: [enum],
    conflicting_atom_ids: [string]
}

ToolPlanV1 = {
    window_id: string,
    pass_id: 0 | 1,
    step_ordinal: int64,
    selected_action: ToolActionV1 | null,
    gap_snapshot: GapSnapshotV1,
    capability_coverage: [enum],
    priority_tuple: [int64, int64, int64, int64, int64] | null,
    budget_before: BudgetViewV1,
    budget_after_if_executed: BudgetViewV1,
    reason_codes: [enum],
    stop_reason: enum | null
}
```

```text
BudgetViewV1 = {
    remaining_window_units: int64,
    remaining_video_units: int64,
    spent_window_units: int64,
    spent_video_units: int64
}
```

- Capability enum 固定为 `SCENE | ENTITY | ACTION | RELATION | TIME | VISIBLE_TEXT | AUDIO_EVENT | SPEECH | MOTION`。
- `fixed_cost` 必须来自 freeze manifest 引用的独立 profiling 表，是正整数。
- `priority_tuple` 精确对应 `(request coverage, conflict coverage, missing coverage, -cost, -order)`。
- STOP plan 的 `selected_action` 和 `priority_tuple` 必须为 null，`budget_before==budget_after_if_executed`。
- `reason_codes` 只能引用 requirement、gap、conflict、request、availability、failure 和 budget，禁止包含期望方向。
- Stop enum 为 `STOP_GAPS_CLOSED | STOP_NO_LEGAL_ACTION | STOP_BUDGET_WINDOW | STOP_BUDGET_VIDEO | STOP_PASS_COMPLETE | STOP_CONTROLLER_FALLBACK`。

### 6.5 ToolExecutionRecordV1

```text
ToolExecutionRecordV1 = {
    action_key: string,
    tool_plan_message_id: string,
    invocation_id: string,
    input_artifact_hashes: [string],
    requested_interval: TimeIntervalV1,
    started_at_utc: string,
    finished_at_utc: string,
    status: enum,
    output_artifact_refs: [ArtifactRefV1],
    actual_cost_audit: object,
    failure_code: string | null
}
```

Status 为 `SUCCEEDED | EMPTY_VALID | FAILED | UNAVAILABLE | NOT_APPLICABLE`。实际延迟/token/GPU 等只用于成本审计，禁止回写 `fixed_cost` 或当前策略。

### 6.6 质量状态

```text
QualityAssessmentV1 = {
    input_quality: number | null,
    source_confidence: number | null,
    input_quality_method: string | null,
    source_confidence_method: string | null,
    quality_policy: enum,
    validity_gate: 0 | 1,
    base_reliability: number
}
```

`quality_policy` 为：

```text
MEASURED
UNVERIFIED_CONTEXT_ONLY
LEGACY_CONSTANT
NOT_APPLICABLE
```

规则：

- `MEASURED`：两项质量均在 `[0,1]`，`base_reliability=g*Q_in*Q_src`。
- `UNVERIFIED_CONTEXT_ONLY`：至少一项不可得，`validity_gate=0`、`base_reliability=0`，对应 atom 只能是 CONTEXT 或不产生 atom。
- `LEGACY_CONSTANT`：仅允许显式 baseline/mechanism experiment；freeze manifest 必须记录常数、理由和 experiment ID。禁止用于完整主线、B2 主贡献或 Memory 写入。
- `NOT_APPLICABLE`：`validity_gate=0`、`base_reliability=0`。
- `MISSING/FAILED/NOT_APPLICABLE` 工具状态必须令 validity gate 为 0。

### 6.7 EvidenceAtomV1

理论文档中的 `evidence_id` 与后文 `atom_id` 统一为 Schema v1 字段 `atom_id`；不得同时输出两个别名。

```text
EvidenceAtomV1 = {
    atom_id: string,
    modality: enum,
    source_family: enum,
    channel_id: string,
    claim: string,
    entities: [string],
    action: string | null,
    relation: string | null,
    attributes: object,
    interval: TimeIntervalV1,
    status: enum,
    role: enum,
    direction: number,
    quality: QualityAssessmentV1,
    tool_id: string,
    model_version: string,
    prompt_version: string | null,
    artifact_refs: [ArtifactRefV1],
    parent_atom_ids: [string]
}
```

枚举与约束：

```text
modality = VLM | OCR | ACOUSTIC_EVENT | ASR | MOTION | METADATA
source_family = VISUAL | AUDIO | CONTEXT
status = VALID | EMPTY_VALID | MISSING | FAILED | NOT_APPLICABLE
role = RISK | CONTEXT | BOUNDARY
direction in [-1,1]
```

- VLM/OCR/MOTION 必须属于 VISUAL；ACOUSTIC_EVENT/ASR 必须属于 AUDIO；METADATA 必须属于 CONTEXT。
- 当前主线 BOUNDARY atom 不进入风险融合，因为 `b_t=0`。
- `CONTEXT` 必须有 `direction=0`。
- 负方向只允许表示对同一可疑解释的直接反证；普通正常背景必须是 CONTEXT/0。
- `status!=VALID` 时禁止贡献正负证据；缺失/失败信息主要记录在 packet/failure audit 中。
- 生成式工具的多次固定查询或多视图属于同一次 tool observation，不得拆成独立投票 atom；它们只能参与 `source_confidence` 估计。
- `parent_atom_ids` 只引用当前 observation 已存在 atom；JointAssessment 不得成为 atom。
- EvidenceAtom 是最小 observed fact，不具有独立投票权；B2 时间包络使用其所属 EvidencePacket 的唯一 `packet_assessment`。Atom 的 direction/quality 仅用于事实级审计和残余冲突强度。

### 6.8 EvidencePacketV1 与 JointAssessmentV1

```text
PacketAssessmentV1 = {
    direction: number,
    quality: QualityAssessmentV1,
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    assessment_source: enum,
    explanation: string
}

EvidencePacketV1 = {
    packet_id: string,
    window_id: string,
    pass_id: 0 | 1,
    action_key: string,
    channel_id: string,
    source_family: enum,
    requested_interval: TimeIntervalV1,
    observed_intervals: [TimeIntervalV1],
    tool_execution: ToolExecutionRecordV1,
    atoms: [EvidenceAtomV1],
    joint_assessments: [JointAssessmentV1],
    packet_assessment: PacketAssessmentV1,
    packet_status: enum,
    failure_audit_ids: [string]
}

JointAssessmentV1 = {
    direction: number,
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    explanation: string
}
```

- `packet_status` 与 ToolExecution status 同域。
- 一个 packet 可以含多个最小事实 atom，但所有 atom 必须来自同一逻辑工具观察。
- `assessment_source` 为 `ATOM_RULES | JOINT_INTERPRETATION`；无论哪种来源，每个 packet 都只有一个 assessment。
- PacketAssessment 的 supporting/counter IDs 必须属于本 packet atoms；其 direction/quality 是该工具观察进入通道时间包络的唯一 `(d_j,r_j)`。
- `packet_status!=SUCCEEDED` 时 assessment 必须为 direction 0、validity gate 0、空 supporting/counter IDs；负 direction 必须至少引用一条经冻结规则确认的直接反证 atom。
- JointAssessment 只解释既有 atom，可以帮助冻结解释器形成该唯一 PacketAssessment，但不进入 atom 集、Memory observed facts 或成为第二张票。
- `packet_id` 必须是 packet immutable core 的内容哈希 ID。

### 6.9 ModalityEvidenceV1

```text
TemporalSegmentEvidenceV1 = {
    interval: TimeIntervalV1,
    active_atom_ids: [string],
    positive_envelope: number,
    negative_envelope: number,
    duration_weight: number
}

ModalityEvidenceV1 = {
    window_id: string,
    pass_id: 0 | 1,
    channel_id: string,
    source_family: enum,
    target_interval: TimeIntervalV1,
    packet_ids: [string],
    atom_ids: [string],
    temporal_segments: [TemporalSegmentEvidenceV1],
    positive_support: number,
    negative_support: number,
    quality: number,
    direction: number,
    covered_duration_us: int64,
    status: enum
}
```

必须满足：

```text
P_m,N_m,q_m in [0,1]
d_m in [-1,1]
q_m = 1-(1-P_m)(1-N_m)
d_m = (P_m-N_m)/q_m, q_m>0; otherwise 0
q_m*d_m = P_m-N_m
```

- `positive_support=P_m`，`negative_support=N_m`，`quality=q_m`，`direction=d_m`。
- 同一 `(window_id,pass_id,channel_id)` 只能有一个 accepted `ModalityEvidenceV1`。
- 时间片必须无重叠、按 `start_us` 排序并完整覆盖 target interval 的已知与未知部分；未覆盖片段必须显式贡献 `(0,0)`。
- 同通道时间片的正负支持分别使用最大包络，禁止求和或 Noisy-OR。
- `duration_weight=segment_duration/target_duration`，全部片段权重之和必须数值等价于 1。

### 6.10 FactConflictPairV1 与 B2OutputV1

```text
FactConflictPairV1 = {
    left_atom_id: string,
    right_atom_id: string,
    temporal_overlap: number,
    contradiction: number,
    pair_strength: number,
    method: string
}

SourceFamilyEvidenceV1 = {
    source_family: VISUAL | AUDIO,
    channel_ids: [string],
    positive_support: number,
    negative_support: number,
    quality: number
}

B2OutputV1 = {
    window_id: string,
    pass_id: 0 | 1,
    target_interval: TimeIntervalV1,
    evidence_atoms: [EvidenceAtomV1],
    modality_evidence: [ModalityEvidenceV1],
    source_family_evidence: [SourceFamilyEvidenceV1],
    positive_support: number,
    negative_support: number,
    q_local: number,
    d_local: number,
    kappa_direction: number,
    kappa_fact: number,
    kappa_local: number,
    e_local: number,
    u_local: number,
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    conflicting_atom_pairs: [FactConflictPairV1],
    covered_fields: [enum],
    unknown_fields: [enum],
    derivation_trace_hash: string
}
```

字段对应理论记号：

```text
positive_support = A_t
negative_support = N_t
q_local = Q_t
d_local = sign(A_t-N_t)*max(A_t,N_t)/Q_t, if Q_t>0; else 0
kappa_direction = min(A_t,N_t)/max(A_t,N_t), if max>0; else 0
kappa_fact = max eligible contradiction pair strength, or 0
kappa_local = 1-(1-kappa_direction)(1-kappa_fact)
e_local = q_local*(1-kappa_local)*d_local
u_local = 1-q_local*(1-kappa_local)*abs(d_local) = 1-abs(e_local)
```

约束：

- Visual Family 由 VLM/OCR/optional Motion 取 max envelope；Audio Family 由 Acoustic/ASR 取 max envelope。
- Visual 与 Audio 之间分别对正向、负向和 quality 使用 Noisy-OR。
- CONTEXT family 不进入 `A/N/Q`。
- supporting/counter IDs 只能引用当前 B2Output 中 VALID observed atoms。
- conflicting pair 必须来自不同来源族、时间相交、指向同一事实槽且尚未被正负方向冲突重复计算。
- B2Output 是本地不可变观察记录。B5/B6 可以读取，禁止回写。

### 6.11 EvidenceRequestV1

```text
EvidenceRequestV1 = {
    window_id: string,
    pass_id: 1,
    missing_capabilities: [enum],
    conflicting_atom_ids: [string],
    fields_to_verify: [enum],
    request_reason: enum,
    remaining_budget_view: BudgetViewV1,
    source_b6_trace_hash: string
}
```

`request_reason` 为 `INTERNAL_MEMORY_DISAGREEMENT | LOCAL_MEMORY_DISAGREEMENT | BOTH`。禁止包含期望异常类别、正负方向、目标分数、case direction 或确认性自然语言。

### 6.12 RetrievalKeyV1

```text
TemporalRelationV1 = {
    left_fact_key: string,
    relation: enum,
    right_fact_key: string,
    evidence_atom_ids: [string]
}

RetrievalKeyV1 = {
    entities: [string],
    actions: [string],
    relations: [string],
    scene_context: [string],
    audio_events: [string],
    ocr_tokens: [string],
    modality_mask: [enum],
    temporal_structure: [TemporalRelationV1],
    physical_duration_us: int64,
    semantic_embedding: {
        values: [number],
        dimension: int64,
        model_id: string,
        model_hash: string,
        normalized: true,
        vector_hash: string
    } | null,
    canonical_serialization: string,
    canonical_serialization_hash: string
}
```

Temporal relation enum 为：

```text
BEFORE | AFTER | MEETS | OVERLAPS | DURING | CONTAINS |
STARTS | FINISHES | EQUALS
```

必须满足：

- 所有事实字段只来自当前 B2 atoms 或 Episode 内当前视频 B2 atoms。
- 非空 `semantic_embedding` 必须由 observation-only canonical facts 通过冻结模型生成并 L2 归一化。当前 query 或 Session case 的 embedding 失败时可以为 null，此时 dense view 为 unavailable，不能补零向量或默认相似度。
- 无时间戳时不得猜测 temporal relation。
- 缺失字段在 canonical serialization 中写为 `UNKNOWN`。
- 禁止包含 `q/d/kappa/u/e/z`、B4 state/path、Salient/Reference role、R/C/novelty/weight、reservoir key、retrieval count、AdvisoryPayload、标签或类别。
- 规范序列化字段顺序固定为 `ENTITIES, ACTIONS, RELATIONS, SCENE_CONTEXT, AUDIO_EVENTS, OCR_TOKENS, MODALITY_MASK, TEMPORAL_RELATIONS, PHYSICAL_TIME`。

### 6.13 AdvisoryPayloadV1 与 ProvenanceV1

```text
AdvisoryPayloadV1 = {
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    q_case: number,
    d_case: number,
    kappa_case_audit: number,
    u_case: number,
    case_reliability_R: number,
    directional_consistency_C: number,
    temporal_trace: [EpisodeWindowTraceV1],
    audit_summary: {
        peak_positive_evidence: number,
        peak_negative_evidence: number,
        physical_duration_us: int64,
        state_path: [enum],
        mean_uncertainty: number,
        fast_slow_disagreement: number,
        modality_coverage: object
    }
}

ProvenanceV1 = {
    case_id: string,
    source_video_hash: string,
    interval: TimeIntervalV1,
    protocol: enum,
    stream_position: int64 | null,
    versions: VersionSetV1,
    artifact_refs: [ArtifactRefV1],
    termination: enum,
    memory_scope: enum,
    episode_role: SALIENT | REFERENCE,
    source_prediction_freeze_hash: string | null,
    source_atom_ids: [string]
}
```

```text
EpisodeWindowTraceV1 = {
    window_id: string,
    interval: TimeIntervalV1,
    q_local: number,
    d_local: number,
    kappa_local: number,
    e_local: number,
    u_local: number,
    b4_state: enum
}
```

- `case_reliability_R == q_case`。
- `directional_consistency_C` 按 Episode 方向质量公式计算。
- 当总方向质量大于 0 时，`kappa_case_audit=1-C`；总方向质量为 0 时固定为 0。它只用于审计，不进入 B6，B6 使用 `R/C/d`。
- `u_case=1-q_case*abs(d_case)`。
- supporting/counter IDs 必须属于 provenance 的当前视频 source atom IDs。
- `termination` 为 `CLOSED_BY_STATE | TRUNCATED_BY_VIDEO_END | REFERENCE_INTERVAL_END`。
- `memory_scope` 为 `SESSION | LONG_TERM`。
- role、state path 和方向载荷均不得暴露给检索排序器。

### 6.14 EpisodicCaseV1、CandidateCaseV1 与 MemoryCaseRecordV1

```text
EpisodicCaseV1 = {
    retrieval_key: RetrievalKeyV1,
    advisory_payload: AdvisoryPayloadV1,
    provenance: ProvenanceV1
}

CandidateCaseCoreV1 = {
    candidate_id: string,
    case_core: EpisodicCaseV1
}

CandidateLifecycleRecordV1 = {
    candidate_id: string,
    candidate_revision: int64,
    previous_lifecycle_hash: string | null,
    lifecycle_state: enum,
    hard_gates: {
        protocol: 0 | 1,
        provenance: 0 | 1,
        observation: 0 | 1,
        write_firewall: 0 | 1
    },
    novelty: number | null,
    admission_weight: number | null,
    reservoir_uniform_draw: number | null,
    reservoir_key: number | null,
    reservoir_log_key: number | null,
    prediction_freeze_hash: string | null,
    discard_reason: string | null,
    lifecycle_hash: string
}

CandidateCaseV1 = {
    core: CandidateCaseCoreV1,
    lifecycle: CandidateLifecycleRecordV1
}

MemoryCaseRecordV1 = {
    case_id: string,
    case_core: EpisodicCaseV1,
    admitted_memory_version: int64,
    reservoir_key: number,
    reservoir_log_key: number,
    capacity_region: enum,
    independent_occurrence_count: int64,
    occurrence_provenance_hashes: [string],
    directional_agreement_audit: int64,
    directional_conflict_audit: int64
}
```

Episode/Candidate 总生命周期为：

```text
OPEN_EPISODE -> QUARANTINED_CANDIDATE -> ELIGIBLE -> ADMITTED | DISCARDED
```

`OPEN_EPISODE` 属于 Episode event，不存在 Candidate core。Candidate 的第一个 lifecycle revision 固定为 `QUARANTINED_CANDIDATE`，revision 从 0 开始；每次状态推进都追加新 revision，`previous_lifecycle_hash` 指向上一版，禁止原地修改。`core` 和 `candidate_id` 在所有 revision 中不变。

`capacity_region` 为 `SALIENT_GUARANTEE | REFERENCE_GUARANTEE | SHARED_OVERFLOW`。

必须满足：

```text
G = product(hard_gates)
R = q_case
nu in [0,1]
W = G*R*nu
reservoir_key = U^(1/W), only if W>0 and U in (0,1)
reservoir_log_key = ln(U)/W
```

- `W=0` 不占新槽位。
- QUARANTINED revision 的 novelty/weight/U/key 可以为 null；完成当前 snapshot 上的 novelty 计算后，ELIGIBLE revision 必须填入 novelty/weight，且 W>0 时同时填入 U、key 和 log key。Reservoir 比较使用与理论 key 单调等价的 `reservoir_log_key`，避免极小 W 下 key 下溢；`reservoir_key` 保留作理论审计。
- LONG_TERM Candidate 的 embedding 不可得时无法计算 diversity novelty，固定 `novelty=0`、`W=0` 并显式 discard；不得用常数 novelty 绕过。Session 检索仍可使用 sparse/temporal view。
- 完全重复只合并独立出现次数和 provenance audit，不改变原案例事实、方向、R、C 或 reservoir key。
- retrieved case IDs 与新案例 observed parent/source atom IDs 必须不相交。
- B5 retrieved payload、B6 advice、retrieval count、历史一致意见不得参与 case core、R、C、d 或 W。
- Candidate 可在 Episode 关闭时构建；只有跨视频 LONG_TERM admission 必须等待整视频 Prediction Freeze 和 Write Permit。
- `hard_gates.protocol` 按 scope 解释：SESSION 要求 Episode 覆盖的全部 B4Decision 已提交、Episode 已关闭且该前缀不可变；LONG_TERM 要求整视频 PredictionFreezeRecord 已接受。两种 scope 都要求 ground truth 不可见。
- SESSION case 的 `prediction_freeze_hash` 必须为 null；LONG_TERM Candidate 进入 Reservoir 前必须绑定非空且匹配的 prediction freeze hash。
- 同一个 Episode 若先发布 SESSION、视频冻结后再候选为 LONG_TERM，必须创建两个 scope 不同的 immutable case wrapper；它们可以共享 observation core hash，但 `memory_scope`、freeze provenance 和 case ID 不同。禁止把 SESSION provenance 原地改成 LONG_TERM。
- `case_id` 由完整 immutable EpisodicCase 在 `provenance.case_id` 省略时计算，随后写回 provenance；`candidate_id` 由 Candidate core 在 candidate ID 省略时计算。

### 6.15 SessionCasePublishV1

```text
SessionCasePublishV1 = {
    candidate_id: string,
    video_id: string,
    closed_at_window_ordinal: int64,
    visible_from_window_ordinal: int64,
    case_hash: string,
    hard_gates_passed: boolean,
    expires_at_video_end: true
}
```

这是当前视频内临时发布，不是跨视频 Reservoir 写入：

- 必须在 Episode 已关闭和 B4 历史状态已提交后发生；
- `visible_from_window_ordinal` 必须严格大于 Episode 最后窗口 ordinal；
- 只能被同视频后续窗口读取，视频结束必须销毁可变 Session 索引；
- 不要求视频级 WritePermit，但必须写入 `memory_events.jsonl`；
- 不得使活动中的 Episode 检索自身；
- `ZS-Independent-Offline` 即使允许完整视频，也必须使用冻结的 episode/window order，禁止当前 Episode 或未来未关闭 Episode 自检索。

### 6.16 RetrievalQueryV1 与 RetrievalManifestV1

```text
RetrievalQueryV1 = {
    window_id: string,
    pass_id: 0 | 1,
    query_scope: CURRENT_WINDOW_ONLY,
    partial_observation: true,
    query_atom_ids: [string],
    retrieval_key: RetrievalKeyV1,
    readable_memory_snapshot_id: string,
    readable_memory_version: int64,
    protocol_cutoff: CausalTimeV1
}

RankingCandidateAuditV1 = {
    case_id: string,
    dense_rank: int64 | null,
    sparse_rank: int64 | null,
    temporal_rank: int64 | null,
    rrf_score_audit_only: number | null,
    reranker_logit_audit_only: number | null,
    final_rank: int64 | null,
    retrieval_key_hash: string,
    advisory_payload_hash: string
}

RetrievalManifestV1 = {
    manifest_id: string,
    observation_only_query_hash: string,
    query_atom_ids: [string],
    readable_memory_snapshot_id: string,
    readable_memory_version: int64,
    available_views: [enum],
    ranking_trace: [RankingCandidateAuditV1],
    ordered_top_k_case_ids: [string],
    case_payload_hashes: [string],
    k_ret: int64,
    B_ret: int64,
    c_rrf: int64,
    model_and_tokenizer_versions: VersionSetV1,
    fallback_reason: string | null,
    persisted: true
}
```

View enum 为 `DENSE | SPARSE_BM25 | TEMPORAL`。规则：

- `B_ret=min(3*k_ret, readable case count)`。
- 某 view 不可用时不贡献 rank；UNKNOWN 不是负相似度。
- final order 为 reranker logit 降序、RRF 降序、RetrievalKey hash 升序；reranker 失败时为 RRF 降序和 hash 升序。
- `ordered_top_k_case_ids` 与 payload hashes 必须一一对应且长度不超过 `k_ret`。
- 空 query atoms 或全部 view 不可用必须返回空 manifest，而不是强制检索。
- manifest 的 `persisted=true` 只有在 append-only decision event 成功落盘并 fsync/等价持久化后设置；此前不得解锁 payload。

### 6.17 AdvisoryBundleV1

```text
AdvisoryCaseV1 = {
    case_id: string,
    rank: int64,
    case_reliability_R: number,
    directional_consistency_C: number,
    historical_direction_d: number,
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    advisory_payload_hash: string,
    provenance_ref: ArtifactRefV1,
    provenance_hash: string
}

AdvisoryBundleV1 = {
    frozen_manifest_hash: string,
    ordered_cases: [AdvisoryCaseV1],
    bundle_hash: string
}
```

- ordered cases 必须逐项匹配 manifest 的 case ID、顺序和 payload hash。
- Memory Agent 禁止返回最终建议分数、`lambda`、`e_commit`、B4 state 或任何可覆盖 B6/B4 的值。
- RRF score、reranker logit、novelty、role、reservoir key 和 retrieval count 禁止进入 AdvisoryCase。
- hash 不匹配时整个 bundle 被拒绝，Decision 使用 Memory abstain/identity，不允许部分信任。

### 6.18 B6DecisionEvidenceV1 与 B6TraceV1

```text
B6DecisionEvidenceV1 = {
    window_id: string,
    source_b2_output_hash: string,
    source_retrieval_manifest_hash: string | null,
    e_commit: number,
    reliability_commit: number,
    d_commit: number,
    u_commit: number,
    memory_status: enum,
    reobserve_pass_count: 0 | 1,
    trace_hash: string
}

B6TraceV1 = {
    local_evidence: number,
    local_reliability: number,
    local_uncertainty: number,
    frozen_top_k_case_ids: [string],
    reciprocal_rank_weights: [number],
    case_R_C_d: [{case_id, R, C, d}],
    memory_positive_mass: number,
    memory_negative_mass: number,
    memory_quality: number,
    memory_conflict: number,
    memory_reliability: number,
    memory_signed_evidence: number,
    fusion_gate: number,
    proposed_evidence: number,
    proposed_reliability: number,
    proposed_direction: number,
    proposed_uncertainty: number,
    internal_memory_disagreement: boolean,
    local_memory_disagreement: boolean,
    reobserve_recommended: boolean,
    reobserve_authorized: boolean,
    reobserve_pass_count: 0 | 1,
    memory_status: enum,
    committed_evidence_tuple: {e, reliability, d, u},
    supporting_atom_ids: [string],
    counter_atom_ids: [string],
    failure_codes: [string]
}
```

`memory_status` 为：

```text
DISABLED_IDENTITY
EMPTY_IDENTITY
UNAVAILABLE_IDENTITY
FUSED
ABSTAIN_UNRESOLVED_CONFLICT
REJECTED_MANIFEST_MISMATCH
```

必须满足：

```text
e_commit = reliability_commit*d_commit
u_commit = 1-abs(e_commit)
abs(e_commit) <= reliability_commit
```

Identity/abstain 状态必须逐字段等于当前最终 B2 的 `e_local`、`q_local*(1-kappa_local)`、`d_local`、`u_local`。每窗口只能存在一个最终 B6DecisionEvidence；pass 1 只替换尚未提交的候选。

### 6.19 B4DecisionV1 与 MomentumTraceV1

```text
MomentumTraceV1 = {
    window_id: string,
    interval: TimeIntervalV1,
    delta_us: int64,
    local_risk_audit: number,
    reliability: number,
    conflict_audit: number,
    local_uncertainty: number,
    effective_evidence: number,
    h_new_by_channel_us: object,
    effective_observation_clock_us: number,
    scene_age_us: int64,
    tau_fast_us: number,
    tau_slow_us: number,
    alpha_fast: number,
    alpha_slow: number,
    boundary_strength: number,
    fast_before: number,
    fast_after: number,
    slow_before: number,
    slow_after: number,
    slow_prior: number,
    novelty: number,
    adaptive_weight: number,
    momentum: number,
    fast_slow_disagreement: number,
    temporal_uncertainty: number,
    lower_bound: number,
    upper_bound: number,
    state_before: enum,
    state_after: enum,
    transition_reason: enum
}

B4DecisionV1 = {
    window_id: string,
    window_ordinal: int64,
    source_b6_decision_hash: string,
    state_version_before: int64,
    state_version_after: int64,
    anomaly_score_z: number,
    risk_state: enum,
    momentum_trace: MomentumTraceV1,
    decision_hash: string
}
```

Risk state enum 为 `NORMAL | SUSPICIOUS | ABNORMAL | RECOVERING`。约束：

- `state_version_after=state_version_before+1`。
- 同一视频第一窗口 before state 为理论硬重置值，version 为 0。
- 当前主线 `boundary_strength=0`；新视频执行硬重置。
- 视频内尚未出现有效方向证据时保持 `F=S=0`；第一条有效提交证据，或未来扩展中 `b_t=1` 的全新场景，必须令 `fast_after=slow_after=e_commit`，不得套用普通衰减后只写入一部分证据。
- `anomaly_score_z=(momentum+1)/2`，仅为有界排序信念。
- `risk_state` 由冻结 uncertainty band 和滞回表产生。
- risk state 禁止回写 `anomaly_score_z`；相同连续 B4 输入的 Hysteresis on/off 变体必须产生相同 z。
- B4 clocks 的 `h_new`、H、tau、alpha 只读取当前 B2 物理覆盖与质量，不读取历史 case 时长。
- 同一 `(run_id,video_id,window_id)` 只能接受一个 B4Decision，且必须按 window ordinal 串行提交。

### 6.20 PredictionFreezeRecordV1

```text
PredictionFreezeRecordV1 = {
    run_id: string,
    video_id: string,
    protocol_version: string,
    expected_window_count: int64,
    ordered_window_ids: [string],
    ordered_decision_hashes: [string],
    per_video_prediction_ref: ArtifactRefV1,
    prediction_manifest_hash: string,
    decision_event_cursor: int64,
    frozen_at_utc: string
}
```

Orchestrator 只有在窗口集合完整、ordinal 连续、每窗口恰好一个 B4Decision、所有 hash 验证通过且 per-video JSON 已持久化后，才能接受该记录。任何缺失窗口、重复 decision、非连续顺序或未落盘父 artifact 都使冻结失败。

### 6.21 WritePermitV1

```text
WritePermitV1 = {
    permit_id: string,
    run_id: string,
    video_id: string,
    protocol_version: string,
    prediction_manifest_hash: string,
    memory_snapshot_id_before: string,
    memory_version_before: int64,
    permitted_candidate_ids: [string],
    write_scope: LONG_TERM,
    permit_payload_hash: string,
    issued_at_utc: string
}
```

`permit_id` 由 run/video/protocol/prediction hash/memory version/sorted candidate IDs/write scope 规范哈希构造。规则：

- 只有 `ZS_STREAM_CAUSAL` 可以签发 LONG_TERM permit。
- `ZS_INDEPENDENT_*` 请求 permit 必须被拒绝。
- candidate IDs 必须来自当前视频已冻结的 Candidate artifact，且不得含开放 Episode。
- permit 一次性、内容不可变；相同 permit replay 幂等。
- issued time 只审计，不参与 permit ID。

### 6.22 MemoryWriteEventV1

```text
CaseMutationV1 = {
    candidate_id: string,
    case_id: string | null,
    result: enum,
    prior_case_id: string | null,
    evicted_case_ids: [string],
    capacity_region_after: enum | null,
    reason_code: string
}

MemoryWriteEventV1 = {
    permit_id: string,
    prediction_freeze_hash: string,
    memory_snapshot_id_before: string,
    memory_version_before: int64,
    candidate_input_hash: string,
    mutations: [CaseMutationV1],
    memory_version_after: int64,
    memory_snapshot_id_after: string,
    reservoir_state_hash_after: string,
    idempotency_key: string
}
```

Mutation result 为 `ADMITTED | DISCARDED | DUPLICATE_MERGED | EVICTED_BY_COMPETITION`。成功事务必须满足：

```text
permit.memory_version_before == current_memory_version
memory_version_after = memory_version_before + 1
```

- 版本不匹配时禁止盲写；Memory 从同一冻结 Candidate 和最新 snapshot 重算 Reservoir 竞争，不重算预测、B2/B4 或 Candidate core。
- 相同 permit ID 重放不得增加 occurrence、重新抽 U、重复淘汰或再次加版本。
- 一次视频写入作为单个原子 CAS 事务；事务失败不得暴露部分写入。

### 6.23 FailureAuditV1

```text
FailureAuditV1 = {
    failure_id: string,
    code: string,
    severity: enum,
    run_id: string,
    video_id: string | null,
    window_id: string | null,
    pass_id: 0 | 1 | null,
    producer: enum,
    parent_message_ids: [string],
    affected_artifact_refs: [ArtifactRefV1],
    fallback_action: string | null,
    retryable: boolean,
    details: object,
    created_at_utc: string
}
```

Severity 精确为 `RECOVERABLE | VIDEO_FATAL | RUN_FATAL`。`details` 禁止写入 ground truth 内容。失败本身不得创建 EvidenceAtom，除非描述的是独立、有效 observed fact；工具错误字符串只能进入 FailureAudit。

## 7. Schema v1 持久化对象

### 7.1 ExperimentFreezeManifestV1

首次目标预测前必须产生只读 `freeze_manifest.json`：

```text
ExperimentFreezeManifestV1 = {
    schema_version: string,
    protocol_version: string,
    contract_version: string,
    manifest_revision: int64,
    experiment_id: string,
    protocol: enum,
    entry_type: enum,
    dataset_id: string,
    theory_document: ArtifactRefV1,
    contract_documents: [ArtifactRefV1],
    dataset_input_manifest: ArtifactRefV1,
    versions: VersionSetV1,
    prompt_mode: enum,
    sampling_window_config: object,
    source_family_registry: object,
    quality_policy_registry: object,
    b3_tool_registry: ArtifactRefV1,
    b3_cost_table: ArtifactRefV1,
    b3_budgets: object,
    b4_config: object,
    memory_config: object,
    order_manifest: ArtifactRefV1 | null,
    perturbation_manifests: [ArtifactRefV1],
    metric_definition: ArtifactRefV1,
    bootstrap_config: object,
    planned_experiment_ids: [string],
    seeds: object,
    frozen_fields_hash: string,
    created_at_utc: string
}
```

必须明确：

- `prompt_mode` 主设置为 `GENERIC`；Dataset Definition Prompt 必须使用独立兼容 experiment。
- B7 为 disabled；B4 mainline `b_t=0`；B4 后 Gaussian disabled。
- 每个 B3 cost 是独立 profiling 得到的正整数，uniform cost 只能是 debug experiment。
- Stream order 和 reservoir seed 分开冻结；每条 stream 从空 Memory 开始。
- manifest 创建后只读。实现 bug 修复必须创建更高 `manifest_revision` 和新 frozen hash，并记录 bug、影响 run 和重跑范围；禁止原地修改。

### 7.2 RunManifestV1

```text
RunManifestV1 = {
    run_id: string,
    freeze_manifest_hash: string,
    experiment_id: string,
    protocol: enum,
    entry_type: enum,
    dataset_id: string,
    repeat_id: string,
    stream_order_hash: string | null,
    initial_memory_snapshot_id: string,
    started_at_utc: string,
    completed_at_utc: string | null,
    run_status: enum,
    processed_video_ids: [string],
    failed_video_ids: [string],
    final_memory_snapshot_id: string,
    event_stream_hashes: object,
    prediction_manifest_refs: [ArtifactRefV1],
    output_hash_manifest_ref: ArtifactRefV1 | null,
    failure_counts: object,
    resource_audit: object
}
```

Run status 为 `CREATED | RUNNING | INFERENCE_FROZEN | EVALUATED | FAILED | QUARANTINED`。运行后只允许补充状态、时间、资源和输出 hash；不得修改 freeze 字段。

### 7.3 AuditEventEnvelopeV1

三个 append-only 事件流使用统一外壳：

```text
AuditEventEnvelopeV1<T> = {
    schema_version: string,
    event_id: string,
    event_type: string,
    event_sequence: int64,
    idempotency_key: string,
    run_id: string,
    video_id: string | null,
    window_id: string | null,
    pass_id: 0 | 1 | null,
    producer: enum,
    parent_event_ids: [string],
    parent_message_ids: [string],
    payload_hash: string,
    memory_version_before: int64 | null,
    memory_version_after: int64 | null,
    created_at_utc: string,
    payload: T
}
```

- `event_sequence` 在各自文件内从 0 连续递增。
- `idempotency_key` 相同且 payload hash 相同时不追加第二行；相同 key 不同 hash 为 conflicting replay。
- Memory state-changing event 必须有 before/after；其他事件必须为 null。
- 每行一个完整 canonical JSON object，以 UTF-8 LF 结束；禁止更新、删除或重排行。
- 文件级 hash 是所有原始 canonical line bytes 的 SHA-256。

### 7.4 三个事件流

| 文件 | 允许 event type | 规范 payload |
|---|---|---|
| `events/tool_events.jsonl` | `TOOL_PLAN_ACCEPTED`、`TOOL_INVOCATION_STARTED`、`TOOL_EXECUTION_COMPLETED`、`TOOL_FAILURE`、`BUDGET_DEBIT` | ToolPlan、invocation identity、ToolExecution、FailureAudit、Budget delta |
| `events/decision_events.jsonl` | `B2_OUTPUT_ACCEPTED`、`RETRIEVAL_MANIFEST_FROZEN`、`ADVISORY_BUNDLE_ACCEPTED/REJECTED`、`B6_COMMIT_ACCEPTED`、`B4_DECISION_COMMITTED`、`PREDICTION_FROZEN` | 对应 Schema v1 对象或 hash refs |
| `events/memory_events.jsonl` | `EPISODE_OPENED/CLOSED`、`SESSION_CASE_PUBLISHED/EXPIRED`、`CANDIDATE_QUARANTINED/ELIGIBLE/DISCARDED`、`NO_ELIGIBLE_CANDIDATES`、`WRITE_PERMIT_ISSUED`、`MEMORY_CAS_COMMITTED/REJECTED` | Episode/Candidate/Permit/MemoryWriteEvent |

FailureAudit 根据失败所属模块进入对应事件流；同一个 failure 可由其他流引用 failure ID，但禁止复制成多个不同 failure 对象。

### 7.5 WindowArtifactV1

每个窗口必须有一个最终 `window.json`：

```text
WindowArtifactV1 = {
    window_input: WindowInputV1,
    accepted_pass_id: 0 | 1,
    tool_plan_message_ids: [string],
    evidence_packet_message_ids: [string],
    b2_output_ref: ArtifactRefV1,
    retrieval_manifest_ref: ArtifactRefV1,
    advisory_bundle_ref: ArtifactRefV1 | null,
    b6_decision_ref: ArtifactRefV1,
    b4_decision_ref: ArtifactRefV1,
    failure_audit_ids: [string],
    window_artifact_hash: string
}
```

Pass 1 存在时，pass 0 中间 B2/B5/B6 仍保存在事件和 pass artifact 中，但只有 pass 1 final refs 可以进入唯一 B4Decision。不存在 pass 1 时 accepted pass 为 0。

### 7.6 VideoArtifactV1

每个视频必须有一个最终 `video.json`：

```text
VideoArtifactV1 = {
    run_id: string,
    video_id: string,
    protocol: enum,
    stream_position: int64 | null,
    ordered_window_refs: [ArtifactRefV1],
    ordered_b4_decision_hashes: [string],
    episode_refs: [ArtifactRefV1],
    candidate_refs: [ArtifactRefV1],
    prediction_freeze_ref: ArtifactRefV1,
    write_permit_ref: ArtifactRefV1 | null,
    memory_write_event_ref: ArtifactRefV1 | null,
    video_status: enum,
    failure_audit_ids: [string],
    video_artifact_hash: string
}
```

Independent 协议的 write permit 和 cross-video write event 必须为 null。`video_status` 为 `FROZEN | VIDEO_FATAL | QUARANTINED`。

### 7.7 MemorySnapshotV1

```text
MemorySnapshotV1 = {
    snapshot_id: string,
    run_id: string,
    memory_namespace: string,
    protocol: enum,
    memory_version: int64,
    event_cursor: int64,
    capacity_K: int64,
    guarantee_per_role: int64,
    cases: [MemoryCaseRecordV1],
    salient_guarantee_case_ids: [string],
    reference_guarantee_case_ids: [string],
    shared_overflow_case_ids: [string],
    reservoir_rng_algorithm: string,
    reservoir_seed: int64,
    reservoir_state_hash: string,
    case_set_hash: string,
    created_at_utc: string
}
```

- case array 按 case ID 排序；三个区域列表按 reservoir log key 降序、case ID 升序。
- `guarantee_per_role=floor(K/2)`；总 case 数不超过 K，不复制案例填充。
- Snapshot 必须能独立重建 dense/sparse/temporal indexes。
- `current_snapshot.json` 可以是指向 versioned snapshot 的原子指针，但不是唯一事实来源。
- 每次成功 CAS 产生新不可变 snapshot；旧 snapshot 不得原地修改。

### 7.8 OutputHashManifestV1

Inference freeze 后必须生成所有规范 artifact 的相对路径、byte length、SHA-256 和 schema version 清单。该清单自身也要哈希并写入 RunManifest。Evaluator 启动前必须完整验证，不允许只验证 predictions 而忽略 Memory events。

### 7.9 ContractAuditV1

`contract_audit.json` 是契约测试的规范汇总 artifact。Schema 精确为：

```text
ContractAuditV1 = {
    run_id: string,
    contract_version: string,
    schema_version: string,
    protocol_version: string,
    freeze_manifest_hash: string,
    started_at_utc: string,
    completed_at_utc: string,
    tests: [{
        test_id: string,
        level: L0 | L1 | L2 | L3 | L4,
        determinism: STRUCTURAL_EXACT | NUMERIC_EQUIVALENT | PROVENANCE_ONLY,
        status: PASS | FAIL | BLOCKED_ASSET | NOT_APPLICABLE,
        expected_failure: RECOVERABLE | VIDEO_FATAL | RUN_FATAL | NONE,
        observed_failure_code: string | null,
        fixture_hashes: [string],
        assertion_count: int64,
        artifact_refs: [ArtifactRefV1],
        duration_ms_audit: binary64,
        details: object
    }],
    summary: {
        pass: int64,
        fail: int64,
        blocked_asset: int64,
        not_applicable: int64,
        accepted_protocol_violations: int64,
        rejected_protocol_violations: int64,
        duplicate_tool_charges: int64,
        duplicate_b4_updates: int64,
        duplicate_memory_writes: int64,
        replay_field_match_rate: binary64,
        trace_completeness: binary64
    }
}
```

- `contract_version` 精确为 `tfavad.contract-tests/1.0.0`；Schema/protocol version 必须与该 run 一致。
- `tests` 对同一 run 的 `test_id` 唯一并按 `test_id` 排序；`fixture_hashes` 去重后升序。
- `assertion_count` 和所有 count 非负；两个 rate 在 `[0,1]`；audit duration 非负且只用于审计。
- `observed_failure_code` 非 null 时必须属于 12.2-12.4 的冻结目录或 freeze manifest 预注册 extension。
- `details` 禁止包含 ground truth 内容、密钥或未脱敏绝对路径。
- `SKIP` 不是合法最终状态。`BLOCKED_ASSET` 可用于 smoke，但完整发布门要求所有 mandatory tests 具有终态且不被它替代。
- 表中 `SE/NE/PO` 只是测试矩阵的展示缩写；写入 JSON 时必须展开为完整 determinism enum。

## 8. 唯一合法消息与算法阶段顺序

### 8.1 每窗口主线

```text
1. Orchestrator: WindowInput
2. Evidence: base observation and PreflightObservation
3. Controller: ToolPlan(pass 0, step n)
4. Evidence: EvidencePacket(pass 0, step n)
5. Evidence: rebuild B2Output(pass 0)
6. Memory: build observation-only RetrievalQuery
7. Memory: persist RetrievalManifest
8. Memory: unlock and emit AdvisoryBundle
9. Decision: run B6
10a. no reobserve -> commit B6DecisionEvidence
10b. reobserve requested and authorized:
     EvidenceRequest -> ToolPlan(pass 1) -> EvidencePacket(s)
     -> rebuild B2Output -> rebuild/freeze RetrievalManifest
     -> rebuild AdvisoryBundle -> rerun B6 exactly once
11. Decision: commit exactly one B6DecisionEvidence
12. Decision: update B4 exactly once and emit B4Decision
13. Orchestrator: commit WindowArtifact and advance ordinal
```

禁止顺序：

- 在 RetrievalManifest 持久化前读取 AdvisoryPayload；
- B6 后直接修改 B2Output；
- B4Decision 后产生 pass 1 或回滚 B2/B5/B6；
- 对同一窗口提交第二个 B4Decision；
- Memory 直接产生 `e_commit` 或 `z_t`；
- Controller 读取 `d_t`、case direction、B4 state 或 ground truth 决定工具。

### 8.2 Pass 规则

- Pass 0 必须存在。
- Pass 1 仅可由 B6 `reobserve_recommended=true` 引发，并由 B3 根据能力和预算授权。
- 每个 action 在同一 pass 最多执行一次；pass 1 可以重新执行 pass 0 已用 action，但在 pass 1 仍最多一次。
- 同一 pass 的 B3 step ordinal 从 0 连续递增，不得跳号或复用。
- Tool failure 后 action 视为已使用，不自动重试；覆盖同一 gap 的另一 action 可以被选择。
- Pass 1 失败、无预算或仍冲突时禁止 pass 2，B6 必须本地 abstain。
- Score/Frozen Score Entry 没有工具能力时绕过 B3，产生显式 identity/entry adapter audit。

### 8.3 Episode 与 Session 顺序

```text
B4 state NORMAL -> non-NORMAL: open Salient Episode
B4 state non-NORMAL -> NORMAL: close Episode
close -> build quarantined Candidate -> hard gates
-> publish eligible Session Case to later windows only
```

最大连续 NORMAL 区间在区间结束或视频结束时生成一个 Reference Episode，使用 B2 fact semantic medoid，不把每个正常窗口存为案例。视频结束时未关闭 Salient Episode 以 `TRUNCATED_BY_VIDEO_END` 关闭。

### 8.4 每视频跨视频写顺序

```text
all windows B4Decision committed
-> per-video predictions persisted
-> PredictionFreezeRecord accepted
-> Candidate artifacts finalized from current-video B2 only
-> Orchestrator issues WritePermit (Stream only)
-> Memory validates freeze + permit + current memory version
-> atomic Reservoir CAS
-> MemoryWriteEvent + new MemorySnapshot
```

禁止 `WriteCurrentVideo -> RetrieveCurrentVideo -> PredictCurrentVideo`。当前视频在它自己的 Prediction Freeze 前不得进入 Long-Term readable snapshot。

### 8.5 三种协议的 Memory 行为

| 行为 | Offline Independent | Causal Independent | Stream Causal |
|---|---:|---:|---:|
| 同视频已关闭 Episode 可检索 | 是 | 是 | 是 |
| 同视频活动 Episode 可检索 | 否 | 否 | 否 |
| 更早视频 Long-Term 可检索 | 否 | 否 | 是 |
| 当前视频 Long-Term permit | 否 | 否 | 预测冻结后是 |
| 视频结束 Session 索引 | 销毁 | 销毁 | 销毁 |
| 视频结束 Long-Term | 空/销毁 | 空/销毁 | CAS 后保留 |

## 9. 状态机、版本与提交所有权

### 9.1 视频窗口状态

```text
CREATED
-> PASS0_ACTIVE
-> PASS0_EVIDENCE_FROZEN
-> OPTIONAL_PASS1_ACTIVE
-> FINAL_EVIDENCE_FROZEN
-> B4_COMMITTED
-> WINDOW_FROZEN
```

状态只能前进。没有 pass 1 时从 PASS0_EVIDENCE_FROZEN 直接到 FINAL_EVIDENCE_FROZEN。任何向前状态缺少所需父 hash 必须拒绝；任何回退请求为协议违规。

### 9.2 B4 视频内状态重置

每个新视频开始必须初始化：

```text
F=0, S=0, scene_age=0, completed_scene_durations=[]
M=0, U=1, state=NORMAL, state_version=0
```

该重置不清除 Stream Long-Term Memory。当前主线每个视频内 `b_t=0`，不得按文件名、标签或指标临时打开边界。

### 9.3 Memory 版本

- `memory_version=0` 表示空 Long-Term Memory 初态。
- 只有成功的整视频 LONG_TERM CAS 可以递增版本。
- Session Case 发布不改变 Long-Term memory version，但仍写 memory event。
- 失败、拒绝或重复 permit 不增加版本。
- 一个 permit 最多对应一个成功 after-version。
- Snapshot 的 event cursor 必须指向产生该版本的最后一条成功 memory event。

### 9.4 冻结与不可变性

对象一旦产生 accepted/frozen event，其 payload/hash 不得修改。修正只能产生：

- 同一 pass 尚未 accepted 的新候选；或
- pass 1 的新对象；或
- 新 manifest revision/new run；或
- CAS 后的新 Memory snapshot。

禁止修改旧 JSON 后保持原 ID/hash。

## 10. 持久化、恢复与派生状态

### 10.1 权威事实来源

权威顺序为：

```text
append-only events
+ immutable per-window/per-video artifacts
+ versioned Memory snapshots
+ freeze/run/output hash manifests
```

SQL/NoSQL 数据库、ANN index、BM25 index、内存对象、缓存和 `current_snapshot` 指针均为派生状态。只要规范 events、case cores 和 snapshot 存在，就必须能重建这些派生状态。

### 10.2 事务边界

- Message acceptance、event append 和对应 artifact rename/commit 必须形成 crash-safe 逻辑事务。
- 允许先写临时文件，但只有内容 hash 验证后才可原子移动到规范路径。
- 进程崩溃后，未产生 accepted event 的临时文件不得被视为有效。
- 已有 accepted tool result 的 replay 必须读取 artifact，不重新调用模型工具。
- Memory CAS 必须原子提交 event、new snapshot 和 current pointer；不能只更新其中一项。

### 10.3 恢复流程

```text
1. 验证 freeze/run manifest
2. 验证三个 event stream sequence、hash 和 parent chain
3. 加载最高完整合法 snapshot
4. 从 snapshot.event_cursor+1 重放 memory events
5. 重建 indexes/caches
6. 对已 accepted window/message 使用 artifact replay
7. 从第一个未冻结逻辑槽继续
```

若 snapshot 与 event log 不一致，以 hash 验证通过的 append-only event 链和更早合法 snapshot 重建；无法建立唯一合法状态时为 fatal，禁止猜测修复。

### 10.4 Retention 与清理

- 规范 events、freeze/run manifests、prediction freeze、per-video/window JSON、Memory snapshots 和 case cores 在实验保留期内不得清理。
- 临时模型输出可以在其 ArtifactRef 已持久化且 retention policy 允许时清理，但 trace 必需的原始输出必须保留或内容寻址归档。
- Independent Session store 必须在视频结束失效；其审计事件和 immutable case artifact 可以保留，但不得被后续视频的 readable snapshot 索引。
- 删除派生 index/cache 不得影响 replay 或指标复算。

## 11. 版本与 Legacy Adapter

### 11.1 精确版本匹配

- 所有消息、artifact、event、snapshot 必须声明 `schema_version`。
- 一个 run 只允许一个精确 Schema/Protocol/Contract 版本组合。
- 任何未知版本或版本不完全相同的对象必须 fail closed；禁止依据“字段看起来相同”自动接受。
- 版本转换只能由 freeze manifest 明确列出的 Legacy Adapter 完成。
- Major/minor/patch 字符串均参与 exact match；兼容性不得由 semver 猜测。

### 11.2 LegacyAdapterReportV1

```text
LegacyAdapterReportV1 = {
    adapter_id: string,
    adapter_version: string,
    source_schema_id: string,
    source_artifact_ref: ArtifactRefV1,
    target_schema_version: string,
    field_mapping: object,
    synthesized_fields: object,
    dropped_fields: [string],
    lossiness: enum,
    quality_policy: enum,
    output_artifact_ref: ArtifactRefV1,
    output_payload_hash: string,
    validation_status: enum
}
```

`lossiness` 为 `LOSSLESS | LOSSY_BASELINE_ONLY | UNADAPTABLE`；validation 为 `ACCEPTED | REJECTED`。

- 只有 LOSSLESS 且通过 Schema v1 全部 invariant 的输出可以进入主线。
- 无法重建 atom-level facts、time interval、quality、source family、provenance 或 label firewall 的对象必须是 `LOSSY_BASELINE_ONLY` 或 `UNADAPTABLE`。
- `LEGACY_CONSTANT` quality 必须是 LOSSY_BASELINE_ONLY，只能进入显式旧基线/机制实验，不能生成 Long-Term Memory case。
- 现有 0-10 score、聚合 modality confidence、含标签/风险分数的 CaseMemoryRecord、`retrieval_confidence` 和旧 score blending 不得静默映射为 Schema v1。
- 旧 `case_memory.jsonl` 与 Schema v1 Memory 必须使用不同 namespace。没有显式 migration report 时禁止混读。

### 11.3 Namespace 规则

```text
memory_namespace = <schema-major>/<protocol>/<run_id>
```

Schema v1 推荐 `v1/<protocol>/<run_id>`。任何旧 namespace 必须只读挂载给 adapter，不能被新写事务原地升级。

## 12. 失败代码、严重度与处置

### 12.1 严重度语义

| 严重度 | 当前单元行为 | Run 行为 | 主结果资格 |
|---|---|---|---|
| `RECOVERABLE` | 使用冻结 fallback，继续 | 继续并计数 | 可保留，但必须报告 |
| `VIDEO_FATAL` | 停止并隔离当前视频，不写 Long-Term | Independent 可继续其他视频；Stream 必须升级 RUN_FATAL | 缺失视频的 run 不得作为完整主结果 |
| `RUN_FATAL` | 停止所有新提交，封存已写 artifact | 标记 FAILED/QUARANTINED | 不得进入主结果 |

在 `ZS_STREAM_CAUSAL` 中，任意 `VIDEO_FATAL` 必须升级为 `RUN_FATAL`，因为跳过或改变一个视频会改变后续 Memory 历史。

### 12.2 RECOVERABLE 代码

| Code | 触发条件 | 必须 fallback |
|---|---|---|
| `TOOL_UNAVAILABLE` | 输入或运行时无该工具 | 字段 UNKNOWN，继续其他合法 action |
| `TOOL_EXECUTION_FAILED` | 工具调用失败 | 记录失败，本 pass 不重试同 action |
| `TOOL_RESULT_INDETERMINATE` | 崩溃后存在 started 事件但无结果，且后端不能按 invocation ID 查询 | 不重调；字段 UNKNOWN 并记录实际成本可能已发生 |
| `TOOL_EMPTY_VALID` | 工具成功但无有效观察 | EMPTY_VALID，不产生正负证据 |
| `QUALITY_INPUT_UNAVAILABLE` | 无可审计 Q_in | context-only 或不产 atom |
| `QUALITY_SOURCE_UNAVAILABLE` | 无可审计 Q_src | context-only 或不产 atom |
| `CONTROLLER_FALLBACK` | Controller 失败 | 使用已有基础观察，禁止自动 All-Tools |
| `STOP_BUDGET_WINDOW` | 窗口预算不足 | STOP，保留当前证据 |
| `STOP_BUDGET_VIDEO` | 视频预算不足 | STOP，保留当前证据 |
| `RETRIEVAL_VIEW_FAILED` | 单个 dense/sparse/temporal view 失败 | 使用剩余 view |
| `RERANKER_FAILED` | cross-encoder 失败 | 使用冻结 RRF order |
| `MEMORY_READ_UNAVAILABLE` | Memory store/read 失败 | 空 manifest，B2 -> B4 identity |
| `ADVISORY_MANIFEST_MISMATCH` | bundle/manifest hash 不匹配 | 拒绝 bundle，identity/abstain |
| `REOBSERVE_UNAVAILABLE` | pass 1 无预算/工具 | 本地 abstain，禁止 pass 2 |
| `UNRESOLVED_MEMORY_CONFLICT` | pass 1 后仍冲突 | 本地 B2 commit |
| `STALE_MEMORY_VERSION` | CAS before version 过期 | 用冻结 Candidate 和最新 snapshot 重算竞争 |
| `DUPLICATE_IDENTICAL_MESSAGE` | 同 key 同 payload | 幂等忽略，不重复计费/状态变更 |

### 12.3 VIDEO_FATAL 代码

| Code | 触发条件 | 处置 |
|---|---|---|
| `INVALID_WINDOW_INTERVAL` | 微秒区间非法或窗口全序冲突 | 停止视频 |
| `CAUSAL_WINDOW_ORDER_VIOLATION` | 读取/提交未来或乱序窗口 | 停止视频 |
| `CONFLICTING_REPLAY` | 同 idempotency key 不同 payload | 拒绝并停止视频 |
| `DUPLICATE_B4_DECISION_CONFLICT` | 同窗口第二个不同 B4Decision | 拒绝并停止视频 |
| `B4_STATE_VERSION_CONFLICT` | state before/after 不连续 | 停止视频 |
| `PREDICTION_FREEZE_INCOMPLETE` | 窗口不完整或 hash/ordinal 不一致 | 不冻结、不签 permit，停止视频 |
| `MESSAGE_PARENT_HASH_INVALID` | 父链或 input hash 不匹配 | 停止视频 |
| `SCHEMA_VALIDATION_FAILED` | 公共对象字段/域不合法 | 停止视频 |
| `ARTIFACT_HASH_MISMATCH` | 当前视频规范 artifact hash 不符 | 停止视频 |
| `EPISODE_CAUSALITY_VIOLATION` | 活动/未来 Episode 被读取 | 停止视频 |

### 12.4 RUN_FATAL 代码

| Code | 触发条件 | 处置 |
|---|---|---|
| `GROUND_TRUTH_ACCESS_VIOLATION` | 任一运行 Agent 请求、接收或推断 annotation payload | 立即隔离 run |
| `INFERENCE_EVALUATION_CONFIG_LEAK` | inference dependency 含标签/指标路径 | 预测前拒绝或运行中立即停止 |
| `FREEZE_MANIFEST_MUTATED` | 冻结字段原地改变 | 停止并创建新 revision 才可重跑 |
| `PROTOCOL_VERSION_MISMATCH` | 版本不精确匹配且无 adapter | 拒绝 run |
| `STREAM_VIDEO_ORDER_VIOLATION` | Stream 视频顺序或初始 Memory 不符 | 停止整条流 |
| `STREAM_VIDEO_FATAL_UPGRADE` | Stream 中发生任一 VIDEO_FATAL | 停止整条流 |
| `MEMORY_EVENT_SNAPSHOT_DIVERGENCE` | 无法从合法 event/snapshot 建立唯一状态 | 隔离 Memory namespace |
| `UNAUTHORIZED_LONG_TERM_WRITE` | 缺 freeze/permit 或 Independent 写入 | 拒绝写并停止 run |
| `OUTPUT_HASH_MANIFEST_INVALID` | inference freeze 的规范输出无法完整验证 | 禁止 Evaluator 启动 |
| `NONDETERMINISTIC_CONTROL_DIVERGENCE` | 相同结构输入重放产生不同控制/状态结果 | 隔离 run，作为实现缺陷 |

### 12.5 重试语义

- 工具 action 在同一 pass 自动重试次数固定为 0。
- 网络/进程层重试只有在可证明原调用未被接受/计费，或通过相同 invocation id 查询幂等结果时允许；不得生成新逻辑 action。
- Stale CAS 可以重算 Reservoir，不得重新抽 candidate 的 U，也不得重新运行模型或预测。
- Fatal 错误禁止原地“修好后继续”主 run；必须保留失败证据，修复后以新 run/revision 重放。

## 13. 并发、总序与 exactly-once

### 13.1 允许的并发

- 单个 ToolAction 内部的冻结多视图/多查询可以并行，但必须压缩为一个 EvidencePacket 和一个 channel vote。
- Independent Offline 的无状态工具获取可以跨窗口并行；B4、Session Episode 和窗口冻结仍按 ordinal 串行提交。
- Independent Causal 可以跨视频并行，但每个视频内状态提交严格串行。
- Stream 的无状态媒体预处理可以预取，但任何会读取/影响 Memory、B3/B5/B6/B4 或对下游可见的提交必须按 stream position 串行。
- 同一 B3 自适应循环中的 action 逻辑上逐步执行：前一 action 的 EvidencePacket 和重建 B2Output 接受后，才能选择下一 action。

### 13.2 冻结提交总序

状态提交键固定为：

```text
(
  stream_position_or_zero,
  video_id_or_independent_manifest_position,
  window_ordinal_or_video_sentinel,
  phase_ordinal,
  message_id
)
```

`phase_ordinal` 由消息链冻结，至少满足：WindowInput < ToolPlan < EvidencePacket < B2 < RetrievalManifest < AdvisoryBundle < B6 < B4 < PredictionFreeze < WritePermit < MemoryWrite。

线程完成时间、wall-clock timestamp、文件枚举顺序和数据库返回自然顺序不得决定提交顺序。

### 13.3 Exactly-once 边界

以下效果必须 exactly once：

- 每个逻辑 ToolAction 的预算扣减和计费 audit；
- 每个 `(window,pass,step)` 的 accepted ToolPlan/EvidencePacket；
- 每个窗口的 B4 state version 增量；
- 每个 Episode open/close 和 Session publish；
- 每个 permit 的 Long-Term CAS；
- duplicate merge 的 occurrence count 增量。

重复投递可以重复验证和读取，但不能重复产生上述效果。

### 13.4 乐观计算与丢弃

实现可以预计算尚未提交的纯函数结果，但必须：

- 绑定完整 input/config hash；
- 不读取协议禁止信息；
- 在父状态版本不匹配时丢弃而非强行提交；
- 不把丢弃计算计入 accepted artifact；成本 audit 仍应记录实际资源消耗。

## 14. 确定性与来源要求

### 14.1 三级确定性标注

每个公开字段/测试必须标注以下等级之一：

| 等级 | 要求 | 典型对象 |
|---|---|---|
| `STRUCTURAL_EXACT` | 字节规范化后结构/枚举/顺序/ID/hash/状态完全相同 | ToolPlan、manifest、top-k IDs、state、events、Memory effects |
| `NUMERIC_EQUIVALENT` | 同字段结构，数值满足 abs/rel tolerance | B2/B6/B4 连续量、相似度 audit |
| `PROVENANCE_ONLY` | 不要求跨硬件输出相同，但必须完整记录输入、版本、seed、配置和 raw artifact | VLM/ASR/OCR/cross-encoder 推理原始输出 |

三级标注不会显著改变运行算法；它只避免错误地要求不同硬件模型推理 bitwise identical，同时保持控制面和状态变化可复现。

确定性比较的前提必须显式声明：`STRUCTURAL_EXACT` 和 `NUMERIC_EQUIVALENT` 针对相同 freeze manifest、相同规范输入 artifact hashes 和相同已接受模型 raw-output artifacts 的执行或 replay。重新在不同硬件上调用只满足 `PROVENANCE_ONLY` 的模型时，原始输出可以不同；这些运行必须具有不同 input/output artifact hash，不能伪装成同一 replay。

### 14.2 结构结果要求

以下必须 `STRUCTURAL_EXACT`：

- ID、hash、schema/version、window/stream order；
- ToolPlan action、priority tuple、reason/stop code 和预算变化；
- source-family grouping、atom/channel membership 和 conflict pair membership；
- Retrieval view availability、ordered top-k case IDs 和 fallback path；
- EvidenceRequest 是否产生、pass 数和唯一 B4 commit；
- risk state/path、Episode 边界/role、Candidate gate/lifecycle；
- Reservoir 区域、admit/discard/evict/duplicate effects、memory versions；
- manifests、event sequences、parent relationships 和 failures。

### 14.3 数值结果要求

- 所有确定性代数采用 binary64 和文档/参考算法固定运算顺序。
- reduction 必须先按 canonical IDs/时间顺序排序，禁止并行无序 reduction 改变控制边界。
- `NUMERIC_EQUIVALENT` 使用 5.3 容差；验收不得用格式化小数文本比较。
- 进入结构分支前使用统一 tolerance comparator；并列时使用冻结 hash/order tie-break。
- Reservoir `U` 必须由 freeze manifest 指定的可移植 PRNG/哈希到开区间 `(0,1)` 生成，不能依赖语言全局 RNG。精确生成在参考算法文档冻结。

### 14.4 模型推理 provenance

每次非确定模型或硬件相关推理至少记录：

- input artifact hashes 和 canonical prompt hash；
- model/revision/weight hash、tokenizer、runtime/library、device 类型；
- decoding 参数、seed、deterministic flags；
- 原始输出 artifact hash；
- adapter/parser/quality method 版本；
- 开始结束时间、token/cost/resource audit；
- 是否使用固定多视图以及如何压缩为一个 packet。

若后端即使确定配置仍不可消除随机性，主配置必须按 B9 预注册重复 3 次并全部报告；禁止运行到获得理想结果为止。

## 15. Artifact 目录契约

### 15.1 Run 输出根

```text
data/agentic_outputs/
  <dataset_id>/
    <experiment_id>/
      <run_id>/
        freeze_manifest.json
        run_manifest.json
        output_hash_manifest.json
        config/
          inference_config.json
          versions.json
          tool_registry.json
          b3_cost_table.json
          order_manifest.json              # Stream only
        events/
          tool_events.jsonl
          decision_events.jsonl
          memory_events.jsonl
        memory_events/
          manifest.json                    # hash-ref to authoritative events/memory_events.jsonl
          per_video/                       # optional immutable event projections
        windows/
          <video_id>/
            <window_ordinal>/
              pass-0/
                tool_plans.json
                evidence_packets.json
                b2_output.json
                retrieval_manifest.json
                advisory_bundle.json       # nullable/absent only by declared fallback
                b6_trace.json
              pass-1/                      # only when authorized
                ...
              window.json
              b4_decision.json
        videos/
          <video_id>/
            video.json
            predictions.json
            prediction_freeze_record.json
            episodes/
            candidates/
        predictions/
          manifest.json
          <video_id>.json
        memory/
          memory_snapshot.json             # final run snapshot copy/ref
          snapshots/
          cases/
        tool_traces/
        cost_report.json
        contract_audit.json
        evaluation/
          evaluator_config.json
        metrics/
        bootstrap/
        comparison_tables/
```

`predictions/`、`memory/`、`tool_traces/`、`metrics/`、`bootstrap/`、`comparison_tables/` 保留 B9 稳定名称。实现可以增加派生目录，但不得改名或省略适用规范目录。
`memory_events/manifest.json` 必须引用 `events/memory_events.jsonl` 的相对路径、byte length 和 hash；`memory_events/per_video/` 若存在，只是不可变 projection，禁止成为第二套可写事件源。

### 15.2 Operational Memory 根

```text
data/agentic_memory/
  v1/
    <protocol>/
      <run_id>/
        events/
          memory_events.jsonl
        snapshots/
          <memory_version>-<snapshot_id>.json
        cases/
          <case_id>.json
        indexes/
          dense/
          sparse/
          temporal/
        current_snapshot.json
```

Run 输出中的 memory events/snapshot 是可交付审计副本或内容寻址引用，必须与 operational Memory hash 一致。`indexes/` 可删除重建；events、snapshots、cases 不可仅存在数据库中。

### 15.3 Predictions 格式

`predictions/<video_id>.json` 必须至少含 ordered windows、规范微秒区间、辅助 frame fields、`z_t`、risk state、B4 decision hash。Evaluator 的 frame expansion 必须使用冻结 sampling/frame mapping；B4 输出禁止再次 Gaussian。若还需原始论文兼容 score export，必须由显式 adapter 生成独立文件并记录 hash，不得覆盖规范 predictions。

## 16. 明确非目标与禁止捷径

### 16.1 非目标

- 不要求拆成网络服务或多个 OS 进程。
- 不冻结 Python 类名、文件名、函数签名或 DI 框架。
- 不选择具体数据库、ANN、BM25 或任务队列产品。
- 不在本文冻结 VLM/OCR/ASR/reranker 的具体模型实例；精确实例由 freeze manifest 固定。
- 不实现 B7、自适应采样或基于目标结果的时间衰减。
- 不承诺每个模块都提高准确率；负结果必须原样报告。
- 不把 `z_t`、reranker logit、RRF score 或工具 confidence 宣称为校准概率。

### 16.2 禁止捷径

以下实现即使能运行或提高指标，也不合规：

- inference config 接受 annotation path 但“承诺不读取”；
- 用文件名、类别目录、标签统计或指标选择 Prompt、阈值、模型、K、k、seed、顺序或工具成本；
- 缺失质量默认 1，或用任意常数冒充 mainline Q_src；
- 同源重复 caption/clip/query 作为多个独立投票；
- 所有模态直接平均，跳过来源族结构；
- 用当前初步方向、B4 state 或历史建议选择检索案例；
- ordered top-k 未持久化就读取 payload；
- 把 reranker/RRF score 除以常数当 retrieval confidence；
- 把 Memory advice 写入新案例 observed facts、R/C/d 或 RetrievalKey；
- 当前视频预测前写入并检索自身；
- 在 B4 后再次 Gaussian，或让 Hysteresis 改写 z；
- 对同一窗口更新 B4 两次；
- B6 冲突后产生 pass 2 或隐藏工具调用；
- 由运行延迟动态改变 B3 frozen cost；
- 使用 FIFO/数据库自然顺序替代 frozen stream/order tie-break；
- 原地修改 event、snapshot、manifest 或已接受 payload；
- 让数据库/向量索引成为无法从 JSON/JSONL 重建的唯一事实源；
- 让现有 prototype schema 无 adapter 冒充 Schema v1。

## 17. 最低契约验收门

实现进入算法/性能验收前，必须先通过：

1. Schema v1 所有 required 字段、enum、域、时间和 hash test vectors。
2. 三协议的配置与 ground-truth 物理隔离测试。
3. 权限拒绝注入：每个角色禁止读写均被拒绝。
4. 同消息相同 replay 无第二效果；同 key 不同 payload 必须拒绝。
5. 每 pass 每 action 至多一次、每窗口至多两 pass、B4 exactly once。
6. AdvisoryBundle 必须绑定 persisted RetrievalManifest。
7. Empty/unavailable Memory 与明确 `B2 -> B4` identity 逐字段一致。
8. 缺 PredictionFreeze、缺 WritePermit、错误 protocol、stale version 的 Long-Term write 均按冻结语义处理。
9. Stream 在固定 order 下串行 predict-before-write；每次 order run 从空 Memory 开始。
10. 从 events + snapshot 重放产生相同结构对象和 Memory effects。
11. 删除全部 indexes/caches 后可重建并得到相同 top-k 结构结果。
12. Evaluator 在 inference freeze 前无法启动，且其输出无法回写 inference/memory。
13. `T6/T7` 的连续 z 完全相同；`F0` 与 identity 完全相同。
14. 所有失败、UNKNOWN、budget stop、abstain 和 fallback 有计数及父链。

完整逐项测试用例、fixtures 和通过标准由 `03_contract_test_matrix.md` 冻结；本文条款不得等待性能实验才验证。

## 18. Theory Check Record

### 18.1 映射表

| 本文部分 | 理论来源 | 回查结论 |
|---|---|---|
| 1-3 范围、协议、Entry、评估隔离 | B0 7.1-7.11；B9 16.2-16.6、16.22 | 三协议分栏、预测后评估、标签隔离一致 |
| 4 角色和状态所有权 | B8 15.1、15.9 | B6 属于 Decision；Memory 不做最终判断 |
| 5 时间/数值/ID/hash | B2 时间对齐；B4 Dual Clock；B8 15.6 | 微秒左闭右开，frame 辅助；不可变 hash/replay 闭合 |
| 6.2-6.8 工具和 atoms | B1；B2 9.1-9.9；B3 10.1-10.10 | missing 不等于 normal；同源重复无额外票；B3 无方向 |
| 6.9-6.10 B2 聚合 | B2 9.10-9.20 | Visual/Audio 分层、max/Noisy-OR、q/d/kappa/e/u 完整 |
| 6.11-6.17 B5 读取 | B5 12.1-12.17；B8 15.3-15.4 | observation-only query、top-k firewall、R/C/d 延迟解锁 |
| 6.14-6.15 Candidate/Session | B5 12.2-12.14 | State-Delimited、write firewall、角色分仓与 session 因果性一致 |
| 6.18 B6 | B6 13.1-13.11 | rank mass、有界融合、最多一次再观察、identity/abstain 一致 |
| 6.19 B4 | B4 11.1-11.14 | Fast/Slow、Elastic Clock、b=0、Hysteresis 不改 z 一致 |
| 6.20-6.22 视频冻结和写入 | B0 7.5；B8 15.5-15.7 | 双钥匙、predict-before-write、CAS 一致 |
| 7-10 events/snapshot/recovery | B8 15.6-15.10；B9 16.22-16.24 | append-only replay、稳定 artifact 和可追溯性闭合 |
| 11 Legacy/version | Schema v1 工程决策；B2/B5/B8 不变量 | 原型不静默兼容，版本不匹配 fail closed |
| 12 failure | B3 10.8；B5 12.15；B6 13.8；B8 15.8 | 失败均显式，Memory unavailable identity，标签违规 fatal |
| 13 concurrency/exactly-once | B0 7.6；B8 15.6-15.7 | 工具可并行但状态串行，Stream 总序和 exactly-once 一致 |
| 14 determinism/provenance | B0 7.8；B8 15.10；B9 16.15、16.22-16.24 | 结构精确、数值等价、模型 provenance 分级一致 |
| 15 artifact layout | B9 16.23-16.24；仓库路径规范 | outputs/memory 稳定根和论文交付目录均保留 |
| 16-17 禁止项/验收 | B0-B6、B8、B9 全部冻结条件 | 未引入 B7、训练、标签、概率校准或第二状态机 |

### 18.2 工程细化但不改变理论的决议

理论回查发现并在本文闭合了以下表示层歧义：

1. **同一 pass 的多步骤幂等键**：用 `payload_type` 的逻辑 slot 区分 step，同时保留 B8 冻结的 `K_msg` 公式。
2. **Session 发布与跨视频写入**：SessionCasePublish 是当前视频临时可见状态，不改变 Long-Term version；Long-Term 才使用 PredictionFreeze + WritePermit + CAS。
3. **`evidence_id`/`atom_id` 命名**：Schema v1 统一为 `atom_id`，避免双字段漂移。
4. **质量不可得**：使用 `UNVERIFIED_CONTEXT_ONLY` fail closed；`LEGACY_CONSTANT` 只允许声明的 baseline/mechanism run。
5. **数值边界与结构确定性**：统一容差比较和 hash tie-break，保持理论自然边界而避免跨后端微小误差改变状态。
6. **Case audit conflict**：`kappa_case_audit` 仅从方向一致性派生并仅供审计；B6 仍严格只消费理论冻结的 `R/C/d/rank`。
7. **视频级 envelope**：视频级 freeze/permit/write 不属于任一窗口 pass，固定 `window_id=null, pass_id=null`；窗口级消息仍严格使用 0/1。

这些决议没有增加学习参数、目标标签、可调阈值、新 Memory 方向或额外 B4 更新。

### 18.3 最终审查结论

- B0/B1/B2/B3/B4/B5/B6/B8/B9 均有公共输入、输出、所有者、持久化和失败语义。
- B7 明确排除，不存在隐式自适应采样。
- 数据可见性、算法顺序、Memory firewall 和唯一状态更新形成闭环。
- Schema v1 不依赖现有 prototype schema 的 0-10 score、旧 case type、retrieval confidence 或 score blending。
- 工程师可以开始设计内部实现，但任何偏离本文外部行为的方案必须先作为契约变更审查，不能作为局部重构直接合入。
