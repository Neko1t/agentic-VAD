# Multiagents Training-Free Agentic VAD 参考算法

> 文档编号：`TFAVAD-ENG-02`  
> 版本：`1.0.0`  
> 状态：工程参考算法，规范性  
> 前置契约：`docs/engineering_handoff/01_frozen_engineering_contracts.md`  
> 理论基线：`docs/achieved/training_free_agentic_vad_evolution.md`

## 1. 文档目的与实现自由

本文把冻结理论和 Schema v1 转换为逐步骤参考算法。工程实现：

- 必须产生与本文数值、分支、排序、状态和副作用等价的外部行为；
- 可以使用不同的类名、函数拆分、并行框架、数据库或索引；
- 不得交换算法阶段、增加学习参数、使用目标标签、隐藏重试或产生额外 B4/Memory 状态变化；
- 所有伪代码中的 `EMIT/ACCEPT/COMMIT/FREEZE` 都必须产生文档 1 规定的 message/event/artifact hash 链。

本文中的数学运算默认使用有限 binary64。控制分支使用文档 1 的 `abs_tol=1e-12`、`rel_tol=1e-9` 比较器；普通公式不得为了通过测试而提前 round。

## 2. 公共确定性原语

### 2.1 Canonical 比较器

```text
FUNCTION TOL(x, y):
    RETURN max(1e-12, 1e-9 * max(abs(x), abs(y)))

FUNCTION CMP(x, y):
    IF x - y > TOL(x,y): RETURN +1
    IF y - x > TOL(x,y): RETURN -1
    RETURN 0

FUNCTION STRICT_GT(x, y):
    RETURN CMP(x,y) == +1

FUNCTION NUMERIC_EQ(x, y):
    RETURN CMP(x,y) == 0
```

域校验与容差分开：

```text
FUNCTION REQUIRE_UNIT(x):
    IF x < -TOL(x,0) OR x > 1+TOL(x,1):
        FAIL SCHEMA_VALIDATION_FAILED
    RETURN min(1, max(0, x)) only when overshoot is within tolerance
```

超过容差的越界不得 clip。进入容差带的舍入噪声可以规范化为边界 0/1，并在 derivation trace 中保存原值。

### 2.2 稳定集合与排序

```text
FUNCTION CANONICAL_SET(items, normalize_fn):
    normalized = [normalize_fn(x) for x in items]
    reject null/invalid elements
    deduplicate by exact normalized UTF-8 bytes
    RETURN sort ascending by normalized UTF-8 bytes

FUNCTION STABLE_DESC(items, numeric_key, hash_key):
    compare numeric_key with CMP
    if tied, compare hash_key ascending bytewise
```

所有 reduction 在运算前必须按 `(start_us,end_us,canonical_id)` 或算法指定顺序排序。并发 completion order 不得进入 reduction。

### 2.3 长度前缀 tuple 编码

所有概念公式中的字符串连接 `a || b || c` 必须实现为无歧义 tuple encoding：

```text
ENCODE_TUPLE(values):
    for each value:
        bytes = canonical UTF-8 or canonical JSON bytes
        append uint64_be(length(bytes))
        append bytes
```

```text
HASH_TUPLE(values) = SHA256(ENCODE_TUPLE(values))
```

### 2.4 内容 ID

```text
FUNCTION CONTENT_ID(prefix, object, self_fields):
    core = deep copy object
    remove every path in self_fields
    RETURN prefix + SHA256(CANONICAL_JSON(core))
```

父 hash 不属于 self field。例：`atom_id` 从 atom 自身移除，parent atom IDs 保留。

### 2.5 可移植 Uniform(0,1)

Reservoir 禁止调用语言全局 RNG。固定：

```text
FUNCTION DETERMINISTIC_OPEN_UNIT(seed, candidate_id):
    digest = SHA256(ENCODE_TUPLE([
        "TFAVAD-RESERVOIR-U-V1",
        int64_be(seed),
        candidate_id
    ]))
    raw52 = uint64_be(digest[0:8]) >> 12
    U = (raw52 + 0.5) / 2^52
    ASSERT 0 < U < 1
    RETURN U
```

该函数使相同 seed/candidate ID 的 U 在语言和线程间一致，且不因处理顺序改变。

### 2.6 时间区间原语

```text
FUNCTION VALIDATE_INTERVAL(I):
    REQUIRE int64(I.start_us), int64(I.end_us)
    REQUIRE 0 <= I.start_us < I.end_us
    if any frame/FPS field is non-null:
        require all four fields non-null
        require 0 <= start_frame < end_frame_exclusive
        require fps_num>0 and fps_den>0

LENGTH(I) = I.end_us - I.start_us

INTERSECTION(I,J):
    s = max(I.start_us,J.start_us)
    e = min(I.end_us,J.end_us)
    RETURN empty if e<=s else [s,e)

CLIP(I,W) = INTERSECTION(I,W)
```

窗口物理步进：

```text
delta_us(0) = LENGTH(W_0)
delta_us(t) = W_t.start_us - W_(t-1).start_us, t>0
```

必须 `delta_us>0`。若采样系统需要不同首窗口规则，必须在 freeze manifest 中声明并产生不同 sampling config hash；不得运行中推断。

### 2.7 区间覆盖并集与重叠率

```text
FUNCTION UNION_INTERVALS(intervals):
    sort by (start_us,end_us)
    merge overlapping or touching half-open intervals
    RETURN disjoint sorted intervals

MEASURE(intervals) = sum LENGTH(I) over UNION_INTERVALS(intervals)

FUNCTION COVERAGE_OVERLAP_RATIO(current, previous):
    current_u = UNION_INTERVALS(current)
    previous_u = UNION_INTERVALS(previous)
    h = MEASURE(current_u)
    IF h == 0: RETURN 0
    overlap = MEASURE(pairwise intersections of current_u and previous_u)
    RETURN overlap / h
```

分母使用当前观察覆盖长度，所以一个 10 秒 clip 相对上一 10 秒 clip 仅新增 0.5 秒时，`overlap=0.95`。

### 2.8 规范文本序列化

```text
SER(X):
    emit sections in exact order:
      ENTITIES
      ACTIONS
      RELATIONS
      SCENE_CONTEXT
      AUDIO_EVENTS
      OCR_TOKENS
      MODALITY_MASK
      TEMPORAL_RELATIONS
      PHYSICAL_TIME
    each set uses CANONICAL_SET
    temporal relations sort by observed start time, relation, fact keys
    absent section emits literal UNKNOWN
```

SER 禁止读取或输出任何方向、分数、state、role、R/C/novelty、Reservoir 或 Advisory 字段。

## 3. 运行级 B0/B8 调度

### 3.1 算法 R0：预运行冻结验证

**输入**：`ExperimentFreezeManifestV1`、`InferenceConfigV1`。
**输出**：validated immutable run context，或 RUN_FATAL。

```text
ALGORITHM VALIDATE_FREEZE(manifest, config):
    require exact schema/protocol/contract versions
    verify manifest self hash and every ArtifactRef hash
    require config.freeze_manifest_ref.hash == manifest file hash
    require config protocol/entry/experiment/dataset == manifest values
    reject any inference field/dependency containing annotation/label/metric path
    require B7 disabled
    if B4 enabled: require Gaussian-after-B4 disabled
    if main Memory:
        require K=512, k_ret=5, B_ret=15, c_RRF=60, reservoir_seed=0
    if B3 enabled:
        require every cost positive integer
        require cost table source is independent profiling
    if Stream:
        require order manifest, empty memory version 0, fixed reservoir seed
    else:
        require cross-video write scope disabled
    derive deterministic run_id
    atomically persist run_manifest status CREATED
```

任何 freeze 字段不匹配都不能用 CLI 参数覆盖。

### 3.2 算法 R1：Stream 顺序

主顺序：

```text
order_key(video_id) = HASH_TUPLE([dataset_id, video_id, "main"])
sort ascending by (order_key, video_id)
```

顺序敏感性 seed `s`：

```text
order_key_s(video_id) = HASH_TUPLE([
    dataset_id, video_id, "order-" + decimal(s)
])
```

每个 order manifest 必须列出全部 video IDs、keys、final position 和 manifest hash。视频文件枚举顺序不得作为 order。

### 3.3 算法 R2：协议可见性

```text
FUNCTION READABLE_MEMORY(protocol, video_position, window_ordinal):
    readable_session = cases where:
        same video
        episode closed
        visible_from_window_ordinal <= window_ordinal

    IF protocol in Independent:
        readable_long_term = empty
    ELSE:
        readable_long_term = cases where:
            source stream_position < video_position
            source PredictionFreeze verified
            admission memory_version <= snapshot version at video start/current commit

    RETURN frozen union(readable_session, readable_long_term)
```

活动 Episode、当前/未来窗口、当前视频 Long-Term Candidate 和未来视频永不可读。

### 3.4 算法 R3：每视频主循环

```text
ALGORITHM RUN_VIDEO(video, protocol, initial_memory_snapshot):
    reset B4 video state to F=0,S=0,M=0,U=1,state=NORMAL,version=0
    initialize empty Session store and episode builder

    for window in canonical window order:
        final_window = RUN_WINDOW(window)
        COMMIT final_window exactly once
        FEED final B4 state and local B2 trace to episode builder
        publish newly closed eligible Session cases to later windows only

    close open Salient Episode as TRUNCATED_BY_VIDEO_END
    close final Reference interval
    persist ordered predictions and per-video artifact
    freeze all B4 decision hashes
    ACCEPT PredictionFreezeRecord

    if protocol == ZS_STREAM_CAUSAL:
        finalize LONG_TERM candidates from current-video B2 only
        issue WritePermit bound to current memory version
        CAS_UPDATE_RESERVOIR
    else:
        assert no Long-Term permit/event

    expire Session store
    RETURN frozen video artifact and resulting memory snapshot
```

Independent 视频可以并行运行；Stream 的 `RUN_VIDEO(i+1)` 不得读取 Memory，直到 `RUN_VIDEO(i)` 的 CAS 成功并形成 snapshot。

## 4. B1 适配器与质量

### 4.1 算法 Q0：工具输出适配

**输入**：获批 `ToolActionV1`、raw tool artifact、输入质量信号。
**输出**：一个 `EvidencePacketV1` 或 FailureAudit。

```text
ALGORITHM ADAPT_TOOL_OUTPUT(action, raw, quality_signals):
    validate action was accepted in current pass/step
    parse raw output using frozen parser version
    determine tool status

    IF status in FAILED/UNAVAILABLE/NOT_APPLICABLE:
        emit no risk atom
        quality = validity_gate 0, base_reliability 0
        emit FailureAudit when applicable
        RETURN packet with explicit status

    compute Q_in using registered deterministic method
    compute Q_src using registered frozen confidence/consistency method

    IF Q_in or Q_src unavailable:
        IF explicit LEGACY_CONSTANT experiment:
            use declared constant and mark LEGACY_CONSTANT
        ELSE:
            mark UNVERIFIED_CONTEXT_ONLY
            validity_gate=0, base_reliability=0

    extract minimal observed facts
    normalize entity/action/relation/text using frozen normalizer
    assign atom-level audit role/direction using frozen risk interpretation rules
    ordinary background -> CONTEXT and direction 0
    direct counter-evidence -> RISK and negative direction
    run frozen packet risk interpreter over only these atoms
    produce exactly one PacketAssessment with one direction/quality
    PacketAssessment must cite its supporting/counter atom IDs
    JointAssessment may explain this one assessment but is not another vote
    construct atom IDs and packet ID
    RETURN one packet for this logical observation
```

多视图、多次固定 query 或多句输出可以产生多个最小事实 atom，但不能产生多个同 channel vote。

### 4.2 质量单调性

适配器单元测试必须验证：

```text
more valid input coverage cannot decrease Q_in
higher native confidence or same-source consistency cannot decrease Q_src
missing/failed/not-applicable always gives gate 0
r = gate * Q_in * Q_src
```

跨模态一致性禁止进入 Q_src；它由 B2 conflict 处理。

## 5. B2 结构化证据算法

### 5.1 算法 E0：Atom 合法化

```text
ALGORITHM VALIDATE_ATOM(atom, target_window):
    validate schema, source family mapping, status and interval
    window_overlap = CLIP(atom.interval,target_window)
    require quality policy valid for experiment type
    r = validity_gate * Q_in * Q_src
    if status != VALID: r = 0
    if role == CONTEXT:
        require direction == 0
        r may remain for conflict/provenance but atom never votes
    if direction < 0:
        require frozen interpretation trace identifies
        the same suspicious explanation being directly refuted
    require r in [0,1], direction in [-1,1]
    RETURN validated atom, window_overlap and fact reliability r
           for conflict/provenance audit only
```

`EMPTY_VALID`、`MISSING`、`FAILED`、`NOT_APPLICABLE` 不产生 `(P,N)` 支持。

### 5.2 算法 E1：单通道时间分段最大包络

**输入**：目标窗口 `W`、同一 channel 的全部 packets/atoms。
**输出**：唯一 `ModalityEvidenceV1`。

```text
ALGORITHM BUILD_MODALITY_EVIDENCE(W, channel_packets):
    valid = []
    endpoints = {W.start_us, W.end_us}

    for packet in canonical packet order:
        validate all atoms for provenance/conflict use
        validate exactly one packet_assessment
        if packet_assessment.quality.validity_gate==0:
            r=0
        else:
            require non-null Q_in/Q_src in [0,1]
            r = Q_in*Q_src
        d = packet_assessment.direction
        for observed interval I in packet.observed_intervals:
            J = CLIP(I,W)
            if J non-empty and packet.packet_status==SUCCEEDED and r>0:
                valid.append(packet,r,d,J)
                endpoints.add(J.start_us,J.end_us)

    sorted_points = sort endpoints ascending
    segments = consecutive half-open intervals between points

    for segment S in segments:
        active = [(packet,r,d) where S subset of J]
        P_S = max([r*max(d,0) for active], default=0)
        N_S = max([r*max(-d,0) for active], default=0)
        lambda_S = LENGTH(S)/LENGTH(W)
        record segment including uncovered (P=N=0)

    P_m = ordered_sum(lambda_S*P_S)
    N_m = ordered_sum(lambda_S*N_S)
    q_m = 1-(1-P_m)*(1-N_m)
    d_m = (P_m-N_m)/q_m if q_m>0 else 0

    require q_m*d_m numerically equals P_m-N_m
    emit exactly one ModalityEvidence for (window,pass,channel)
```

使用 endpoint partition 可防止重叠 clips 重复累计覆盖时间；同源重复 packet 通过 max envelope 幂等。

### 5.3 算法 E2：来源族融合

```text
ALGORITHM FUSE_SOURCE_FAMILIES(modality_evidence):
    require at most one evidence per channel

    for each channel m:
        a_m = q_m * max(d_m,0)
        n_m = q_m * max(-d_m,0)

    Visual = channels VLM, OCR, optional MOTION
    Audio  = channels ACOUSTIC_EVENT, ASR

    for family g in [VISUAL,AUDIO]:
        A_g = max(a_m in g, default=0)
        N_g = max(n_m in g, default=0)
        Q_g = max(q_m in g, default=0)

    A = 1 - ordered_product_g(1-A_g)
    N = 1 - ordered_product_g(1-N_g)
    Q = 1 - ordered_product_g(1-Q_g)

    D = max(A,N)
    d = sign(A-N)*D/Q if Q>0 else 0
    kappa_dir = min(A,N)/D if D>0 else 0
    RETURN A,N,Q,d,kappa_dir and family trace
```

Noisy-OR 只跨 Visual/Audio 两个冻结家族。Metadata/CONTEXT 不构成第三家族。

### 5.4 算法 E3：残余事实冲突

时间重叠系数固定为 overlap coefficient：

```text
TEMPORAL_OVERLAP(i,j,W):
    I = CLIP(i.interval,W)
    J = CLIP(j.interval,W)
    if I or J empty: return 0
    return LENGTH(INTERSECTION(I,J)) / min(LENGTH(I),LENGTH(J))
```

```text
ALGORITHM RESIDUAL_FACT_CONFLICT(atoms,W):
    candidates = index by overlapping time and normalized fact slots
    best = 0
    pairs = []

    for pair (i,j) in canonical pair order:
        continue unless source_family differs and both are VALID observed atoms
        continue unless times overlap and refer to same entity/action/object/relation slot
        contradiction = frozen rule/NLI continuous score in [0,1]
        continue if contradiction == 0
        continue if pair is already represented as the positive-vs-negative
                    opposition used in kappa_dir
        overlap = TEMPORAL_OVERLAP(i,j,W)
        strength = overlap * min(r_i,r_j) * contradiction
        append audit pair
        best = max(best,strength)

    RETURN kappa_fact=best, canonical audit pairs
```

冻结 NLI score 是代理矛盾强度，不是概率。重复相同 contradiction pair 使用 max，不累加。

### 5.5 算法 E4：最终 B2Output

```text
ALGORITHM BUILD_B2_OUTPUT(W, packets):
    group packets by frozen channel_id
    modality = [BUILD_MODALITY_EVIDENCE(W,group) for group]
    A,N,Q,d,k_dir,family_trace = FUSE_SOURCE_FAMILIES(modality)
    k_fact,pairs = RESIDUAL_FACT_CONFLICT(valid atoms,W)
    kappa = 1-(1-k_dir)*(1-k_fact)
    e_local = Q*(1-kappa)*d
    u_local = 1-Q*(1-kappa)*abs(d)

    require e_local numerically equals (A-N)*(1-k_fact)
    require u_local numerically equals 1-abs(e_local)
    determine supporting/counter IDs from contributing PacketAssessments,
    then resolve their cited valid RISK atom IDs
    determine covered/unknown fields
    emit immutable B2Output
```

支持/反对 ID 的 inclusion 必须有 derivation trace；普通 CONTEXT 不进入 supporting/counter，但可以进入 RetrievalKey scene facts。

## 6. B3 Evidence-Gap Controller

### 6.1 算法 G0：激活需求

```text
R_base = {SCENE,ENTITY,ACTION,RELATION,TIME}

ACTIVATE_REQUIREMENTS(preflight, evidence_request, config):
    R = R_base
    if text region present or unreadable text atom or request asks text:
        R += VISIBLE_TEXT
    if audio track and frozen acoustic precheck active:
        R += AUDIO_EVENT
    if frozen VAD says speech or request asks speech semantics:
        R += SPEECH
    if Motion ablation enabled and motion computable:
        R += MOTION
    R += capabilities explicitly named by EvidenceRequest
    RETURN canonical R
```

Preflight 只描述形态，禁止激活异常类别或方向。

### 6.2 算法 G1：Gap 集合

```text
BUILD_GAPS(R, B2, EvidenceRequest):
    C = fields covered by VALID observed non-pure-context risk atoms
    G_miss = R minus C
    G_conflict = fields referenced by B2 conflicting atom pairs/IDs
    G_request = request capabilities, or empty
    G = union(G_miss,G_conflict,G_request)
    RETURN canonical sets
```

UNKNOWN、失败和纯 CONTEXT 不关闭风险字段 gap。

### 6.3 算法 G2：选择动作

```text
SELECT_ACTION(state, registry):
    legal = []
    for action a in registry ordered by ord(a):
        require avail(a)
        require K_a intersects G
        require a not used in current pass
        require cost(a) <= both remaining budgets
        priority = (
            count(K_a intersect G_request),
            count(K_a intersect G_conflict),
            count(K_a intersect G_miss),
            -cost(a),
            -ord(a)
        )
        legal.append(a,priority)

    if G empty: STOP_GAPS_CLOSED
    if legal empty: STOP_NO_LEGAL_ACTION or precise budget STOP
    else return lexicographic maximum priority
```

优先 tuple 不求和，也不视为概率或 expected information gain。

### 6.4 算法 G3：单 pass 循环

```text
RUN_CONTROLLER_PASS(pass_id, initial_B2, request):
    used = empty
    step=0
    current_B2=initial_B2

    loop:
        R = ACTIVATE_REQUIREMENTS(...)
        gaps = BUILD_GAPS(R,current_B2,request)
        plan = SELECT_ACTION(...)
        EMIT ToolPlan(pass_id,step)

        if plan is STOP: RETURN current_B2,plan.stop_reason

        atomically debit fixed cost once
        used.add(action)
        packet = execute/adapt action exactly once
        EMIT packet/failure
        current_B2 = BUILD_B2_OUTPUT(all accepted packets in this pass context)
        step += 1

        require step <= size(registry)
```

Pass 1 的循环结束后无论原因如何都不得创建 pass 2。Controller 崩溃 fallback 使用已有基础 B2，不调用全部工具。

## 7. B5 Episode 与案例构建

### 7.1 算法 M0：State-Delimited Episode Builder

内部 builder 只维护当前视频窗口 ordinal、已提交 B4 state 和本地 B2 refs：

```text
active_t = (state_t != NORMAL)
```

```text
ALGORITHM FEED_EPISODE_BUILDER(window_t):
    require B4Decision_t committed exactly once

    if first window:
        if active_t:
            open Salient at t
        else:
            open Reference normal interval at t
        return

    if active_(t-1)==false and active_t==true:
        close Reference interval at t-1
        open Salient core at t
        include t-1 as pre-transition context if it exists

    else if active_(t-1)==true and active_t==false:
        include t as post-transition context
        close Salient at t with CLOSED_BY_STATE
        open Reference normal interval at t

    else:
        append t to current core interval
```

视频结束：

```text
if Salient open:
    close at video end with TRUNCATED_BY_VIDEO_END
if Reference open:
    close at video end with REFERENCE_INTERVAL_END
```

规则：

- Salient core 是最大连续 non-NORMAL 状态区间，并额外保存至多一个进入前 NORMAL 窗口和一个返回后 NORMAL 窗口。
- Reference 是最大连续 NORMAL 区间，一个区间只产生一个 Episode，不为每窗口建 case。
- Salient 的边界 context 窗口可以同时属于相邻 Reference 的 core；这是显式上下文重叠，不产生窗口级第二次 B4 更新。
- 全视频 NORMAL 产生一个 Reference。
- 全视频没有有效 B2 observed atom 时不产生可检索 Episode，写 FailureAudit。
- Episode open/close event append-only；open Episode 不可检索。

### 7.2 算法 M1：Reference 语义 medoid

对 Reference core 中每个具有可用 observation-only embedding 的窗口向量 `phi_j`：

```text
DIST(phi_i,phi_j) = 1 - dot(phi_i,phi_j)

MEDOID = argmin_j ordered_sum_l DIST(phi_j,phi_l)
tie-break: window_id hash ascending
```

若任一参与向量不合法，先排除该窗口；若无合法向量，则 Reference RetrievalKey embedding 为 null，Long-Term novelty 固定 0。Reference 的检索事实内容取 medoid 窗口事实，Episode reliability/trace 仍使用整个 Reference core。

该 medoid 只表达稳定背景代表，不是 normal 标签。

### 7.3 算法 M2：Episode 数值摘要

**重要**：全部案例方向、可靠度和 atom IDs 从当前视频本地 B2Output 重算；禁止读取 B6 commit、Memory advice 或最终 z。

```text
ALGORITHM SUMMARIZE_EPISODE(episode_windows):
    T = canonical episode window order including explicit transition context
    total_delta = sum(delta_us_t for t in T)
    require total_delta > 0

    for t in T:
        lambda_t = delta_us_t / total_delta
        r_t = q_local_t * (1-kappa_local_t)
        e_t = r_t * d_local_t

    q_case = ordered_sum(lambda_t*r_t)
    numerator = ordered_sum(lambda_t*e_t)
    d_case = numerator/q_case if q_case>0 else 0
    u_case = 1-q_case*abs(d_case)

    directional_mass = ordered_sum(lambda_t*abs(e_t))
    EPS_CASE = 2^-52
    C = abs(numerator)/(directional_mass+EPS_CASE)
        if directional_mass>0 else 0
    kappa_case_audit = 1-C if directional_mass>0 else 0

    require q_case*d_case numerically equals numerator
    require all outputs bounded
    RETURN q_case,d_case,u_case,C,kappa_case_audit,audit summaries
```

`R=q_case`。不得再乘 `u_case` 或 C 形成 R，避免重复折扣；C 只在 B6 限制方向一致性。

### 7.4 算法 M3：Episode RetrievalKey

Salient key：

```text
phi_case_raw = ordered_sum(lambda_t*phi_t over available vectors)
phi_case = phi_case_raw / L2(phi_case_raw), if norm>0; else null
facts = canonical union of observation-only episode facts
temporal structure = relations directly derivable from atom timestamps
```

Reference key：

```text
phi_case = medoid window embedding, if available
facts = medoid window observation-only facts
physical_duration = full Reference core duration
```

```text
BUILD_RETRIEVAL_KEY(episode):
    include entities/actions/relations/scene/audio/OCR/modality mask
    include only observed timestamp-derived temporal relations
    include physical duration
    build SER and hash
    assert forbidden-field scan is empty
```

Forbidden-field scan 必须拒绝 B4 state/path、q/d/e/u/z、case role、R/C/novelty、retrieval statistics、Advisory 和标签。State path 只进入 Advisory audit summary。

### 7.5 算法 M4：Candidate Core 与 Scope

```text
BUILD_SCOPE_CASE(episode, scope, prediction_freeze):
    summary = SUMMARIZE_EPISODE(local B2 windows)
    retrieval_key = BUILD_RETRIEVAL_KEY(episode)
    advisory = local atom IDs + summary + audit trace
    provenance = source/video/interval/version/artifact/termination/role

    if scope == SESSION:
        provenance.memory_scope=SESSION
        provenance.source_prediction_freeze_hash=null
    else:
        require complete matching PredictionFreezeRecord
        provenance.memory_scope=LONG_TERM
        provenance.source_prediction_freeze_hash=freeze hash

    case_id = content hash with provenance.case_id omitted
    candidate_id = content hash of candidate core with candidate_id omitted
    append QUARANTINED_CANDIDATE revision 0
```

同一 Episode 的 Session 和 Long-Term wrapper 是两个 immutable scope objects。二者可以共享 observation summary hash，但不共享 case/candidate ID。

### 7.6 算法 M5：无标签硬门

```text
HARD_GATES(candidate):
    G_protocol =
        SESSION: episode B4 prefix committed and closed, no GT visible
        LONG_TERM: whole-video PredictionFreeze verified, no GT visible

    G_provenance = all source/video/time/model/prompt/artifact hashes valid
    G_observation = at least one valid current-video B2 atom and q_case>0
    G_write_firewall =
        supporting/counter atom IDs subset of current-video B2 atoms
        all q/d/u/R/C recomputed from local B2
        no retrieved payload/advice/case direction/retrieval count in derivation

    G = product four gates
    if G==0:
        append DISCARDED revision with exact reason
    else:
        append ELIGIBLE revision
    RETURN G
```

Memory case IDs seen during the source video can remain in audit trace, but they cannot be a parent/source atom ID or enter case direction/reliability/facts.

## 8. B5 Long-Term Admission 与 Reservoir

### 8.1 算法 A0：完全重复

完全重复固定为：

```text
duplicate(candidate, resident_case) :=
    candidate.retrieval_key canonical_serialization_hash
      == resident_case.retrieval_key canonical_serialization_hash
    AND candidate.retrieval_key vector_hash
      == resident_case.retrieval_key vector_hash
```

两个 embedding 都为 null 时，第二项视为相等；但 null embedding Long-Term candidate 的 W 固定 0，不会首次 admitted。

重复处理：

- 同一 source provenance hash 的 replay：完全幂等，不增加 occurrence。
- 不同已冻结视频的独立 occurrence：只增加 occurrence/provenance audit。
- 新方向与 resident `d_case` 同非零符号时 agreement audit +1；相反非零符号时 conflict audit +1；零方向不增加二者。
- 不修改 resident facts、R、C、d、role、reservoir key 或 capacity region priority。

### 8.2 算法 A1：Novelty 与准入权重

```text
ALGORITHM ADMISSION_WEIGHT(candidate, current_resident_memory):
    require HARD_GATES == 1
    R = candidate.q_case

    if candidate embedding is null:
        nu=0
    else if current resident memory has no non-null embedding:
        nu=1
    else:
        nu = min_j ((1-dot(phi_candidate,phi_j))/2)

    nu = REQUIRE_UNIT(nu)
    W = R*nu
    if W==0: discard without slot
    U = DETERMINISTIC_OPEN_UNIT(reservoir_seed,candidate_id)
    log_key = log(U)/W
    key = exp(log_key)        # audit value; may underflow to 0
    RETURN nu,W,U,key,log_key
```

Novelty 只比较当前 resident Memory，不维护无界 shadow memory。时间新近度不进入 W。

### 8.3 算法 A2：Role-Stratified Elastic Reservoir

```text
ALGORITHM REPARTITION_RESERVOIR(resident_cases, new_case, K):
    if K==0: return empty, new_case discarded MEMORY_DISABLED
    require K>=2 for role-stratified mode

    pool = resident_cases union {new_case}
    deduplicate by case_id
    b = floor(K/2)

    salient = cases with immutable role SALIENT
    reference = cases with immutable role REFERENCE

    G_s = top min(b,size(salient)) by (reservoir_log_key desc,case_id asc)
    G_r = top min(b,size(reference)) by same order

    L = K-size(G_s)-size(G_r)
    remainder = pool minus G_s minus G_r
    O = top min(L,size(remainder)) by same order

    selected = G_s union G_r union O
    assign regions SALIENT_GUARANTEE/REFERENCE_GUARANTEE/SHARED_OVERFLOW
    evicted = pool minus selected
    require size(selected)<=K
    RETURN selected,evicted,region map
```

单个角色可临时占满 K；稀缺角色到达后先建立自己的保障区。奇数 K 的额外槽位进入 shared overflow。

### 8.4 算法 A3：整视频原子 CAS

```text
ALGORITHM CAS_UPDATE_RESERVOIR(freeze,permit,candidates,current_snapshot):
    verify protocol is Stream
    verify freeze/permit video/run/prediction hashes match
    verify permitted candidate IDs exact

    if permit already committed:
        return previously committed event/snapshot idempotently

    if permit.memory_version_before != current_snapshot.version:
        emit STALE_MEMORY_VERSION
        reject the stale permit
        Orchestrator issues a replacement permit bound to latest version
        using the same prediction freeze and candidate IDs
        rerun only Reservoir competition with same deterministic U values
        do not rerun prediction or models

    working = copy current resident set
    mutations=[]
    for candidate in canonical candidate_id order:
        verify final eligible lifecycle hash and write firewall
        if exact duplicate resident:
            idempotently merge independent occurrence audit
        else:
            compute A1 once
            if W>0:
                working,evicted,regions = A2(working,candidate,K)
            else discard
        append mutation

    build immutable snapshot version+1
    atomically append MemoryWriteEvent, snapshot, current pointer
    RETURN committed event/snapshot
```

候选处理顺序固定为 candidate ID 升序；同一 permit 的所有 mutation 是一个事务，禁止部分可见。
只要 permit 含至少一个 hard-gate eligible candidate，CAS 即使最终全部因 W=0/竞争而 discarded，也提交完整 mutation audit 和 `version+1` snapshot；该版本表示该获准视频写事务已经 exactly once 处理，case set hash 可以保持不变。

## 9. B5 Observation-Only Retrieval

### 9.1 算法 S0：当前窗口 Query

```text
ALGORITHM BUILD_QUERY(final_B2, readable_snapshot):
    atoms = current-window VALID observed atoms
    if atoms empty:
        return empty query and empty manifest

    facts = canonicalize atoms including useful CONTEXT facts
    build RetrievalKey-shaped query without any B4/B6/Memory direction
    attempt frozen embedding:
        on failure set embedding null and mark dense unavailable
    query_scope=CURRENT_WINDOW_ONLY
    partial_observation=true
    bind readable snapshot ID/version and causal cutoff
```

不得拼接滚动风险轨迹、当前 state、初步方向或未来窗口。

### 9.2 算法 S1：Dense View

```text
if query embedding null: view unavailable
for each readable case with non-null embedding:
    score = ordered dot(phi_query,phi_case)
sort by score desc with CMP, retrieval_key_hash asc
return first B_ret
```

Dot score 只在 dense view 内排序，不进入 B6。

### 9.3 算法 S2：BM25 View

Tokenizer、case normalization、大小写和停用词策略必须由 freeze manifest 版本化。Lex 由 entities/actions/relations/scene/audio/OCR 的去重 token 组成。

```text
N = readable document count
df(term) = readable cases containing term
idf(term) = ln(1 + (N-df(term)+0.5)/(df(term)+0.5))

BM25(q,d) = sum over unique query terms:
  idf(term) *
  f(term,d)*(k1+1) /
  (f(term,d)+k1*(1-b+b*dl/avgdl))

k1=1.2, b=0.75
```

IDF/avgdl 只由当前 readable snapshot 计算。`N=0` 或 `avgdl=0` 时 view unavailable。排序为 BM25 降序、RetrievalKey hash 升序，取前 B_ret。

### 9.4 算法 S3：Temporal View

```text
T(X) = set of (action_i, Allen_relation_ij, action_j)
       where relation is directly derived from observed timestamps

if T(query) empty: view unavailable

score(query,case) =
    size(T(query) intersect T(case)) / size(T(query))
```

历史案例额外后续动作不受惩罚。排序为 coverage 降序、RetrievalKey hash 升序，取前 B_ret。

### 9.5 算法 S4：RRF 候选融合

```text
ALGORITHM RRF(view_lists,k_ret,readable_count):
    B_ret = min(3*k_ret,readable_count)
    available = non-failed/non-unavailable views
    if available empty: return empty

    candidates = union top-B_ret IDs from available views
    for case in candidates:
        score=0
        for view in available:
            if case in view:
                score += 1/(60+rank_view(case))
    sort by score desc with CMP, RetrievalKey hash asc
    return first B_ret candidates and audit ranks/scores
```

Rank 从 1 开始。缺失 view 不给正贡献，也不给负贡献。

### 9.6 算法 S5：冻结 Cross-Encoder 重排

```text
for each RRF candidate:
    logit = frozen_cross_encoder(SER(query),SER(case RetrievalKey))
    record raw logit and provenance

sort by:
    logit descending with CMP
    RRF score descending with CMP
    RetrievalKey hash ascending
take first min(k_ret,candidate_count)
```

输入截断、最大长度和 batching 必须在 freeze manifest 中固定；截断禁止读取 AdvisoryPayload。若 reranker 任一批次失败，整个 reranker stage fallback 到完整 RRF order，禁止混合“部分 reranked”列表。

### 9.7 算法 S6：Manifest Freeze 与 Payload 解锁

```text
ALGORITHM FREEZE_AND_UNLOCK(query,ranking):
    build RetrievalManifest with query/snapshot/view/rank/version trace
    persist canonical artifact
    append RETRIEVAL_MANIFEST_FROZEN event
    only after durable acceptance:
        read payload hashes for exact ordered top-k IDs
        verify each against manifest
        construct AdvisoryBundle in same order
    on any mismatch:
        reject whole bundle and return Memory abstain/identity
```

`R/C/d`、role、novelty、reservoir key、retrieval count、RRF score 和 reranker logit 都不能影响 top-k 后的 B6 权重，除 rank/R/C/d 三类冻结输入外其余只审计。

## 10. B6 有界 Memory 融合

### 10.1 算法 F0：Identity Pass

```text
IDENTITY_B6(B2,status):
    r_local = q_local*(1-kappa_local)
    e_local = r_local*d_local
    u_local = 1-abs(e_local)
    RETURN {
        e_commit=e_local,
        reliability_commit=r_local,
        d_commit=d_local,
        u_commit=u_local,
        memory_status=status
    }
```

`status` 为 disabled、empty、unavailable、manifest mismatch 或 unresolved conflict 对应枚举。Identity 必须逐字段计算，不得从旧 score blending 近似。

### 10.2 算法 F1：Rank-Weighted Signed Memory Mass

```text
ALGORITHM MEMORY_MASS(ordered_cases):
    n = size(ordered_cases)
    if n==0: return all-zero memory quantities

    H_n = ordered_sum(1/j for j=1..n)
    for case at rank j:
        omega_j = (1/j)/H_n
        require R,C in [0,1], d in [-1,1]

    A_mem = ordered_sum(omega_j*R_j*C_j*max(d_j,0))
    N_mem = ordered_sum(omega_j*R_j*C_j*max(-d_j,0))
    q_mem = A_mem+N_mem

    if q_mem>0:
        d_mem = (A_mem-N_mem)/q_mem
        kappa_mem = 2*min(A_mem,N_mem)/q_mem
    else:
        d_mem=0; kappa_mem=0

    e_mem = A_mem-N_mem
    r_mem = abs(e_mem)
    coherent_direction = sign(e_mem) if r_mem>0 else 0
    u_mem = 1-r_mem

    require A_mem+N_mem <= 1 within tolerance
    RETURN all quantities and omega list
```

Case rank 从 manifest 的 1-based final order 读取；禁止用 raw similarity/logit 代替。

### 10.3 算法 F2：Uncertainty-Gated Bounded Fusion

```text
ALGORITHM PROPOSE_FUSION(B2,memory_mass):
    r_local = q_local*(1-kappa_local)
    e_local = r_local*d_local
    u_local = 1-abs(e_local)

    lambda = u_local*r_mem
    e_hat = (1-lambda)*e_local + u_local*e_mem
    r_hat = (1-lambda)*r_local + lambda
    d_hat = e_hat/r_hat if r_hat>0 else 0
    u_hat = 1-abs(e_hat)

    require lambda,r_hat,u_hat in [0,1]
    require e_hat,d_hat in [-1,1]
    require abs(e_hat)<=r_hat within tolerance
    RETURN proposed tuple and trace
```

高可靠本地观察使 `u_local` 低，自动限制 Memory；本地弱且历史一致时 Memory 才有较大影响。

### 10.4 算法 F3：无阈值冲突与 EvidenceRequest

```text
internal_disagreement = STRICT_GT(A_mem,0) AND STRICT_GT(N_mem,0)
local_disagreement = CMP(e_local*e_mem,0) == -1
uncertainty_not_improved = CMP(u_hat,u_local) >= 0

reobserve_recommended =
    STRICT_GT(q_mem,0)
    AND (internal_disagreement OR local_disagreement)
    AND uncertainty_not_improved
```

若 recommended，EvidenceRequest 只包含：

- 当前 B2 中缺失 capability；
- 产生 conflict 的 atom IDs；
- 需要核验的事实字段；
- 无方向 reason；
- 当前预算 view。

不得包含 `e_mem` 符号、目标方向、case 类别或“寻找支持证据”。

### 10.5 算法 F4：每窗口 B6 控制

```text
ALGORITHM RUN_B6(final_B2,manifest,bundle,pass_count):
    if Memory disabled: return IDENTITY_B6(DISABLED_IDENTITY)
    if manifest/bundle unavailable or empty:
        return IDENTITY_B6(corresponding identity status)
    if bundle hash binding invalid:
        return IDENTITY_B6(REJECTED_MANIFEST_MISMATCH)

    mass = MEMORY_MASS(bundle ordered cases)
    proposal = PROPOSE_FUSION(final_B2,mass)
    recommended = F3(...)

    if recommended and pass_count==0:
        emit EvidenceRequest(pass_id=1)
        return PENDING_REOBSERVATION, not a B4 commit

    if recommended and pass_count==1:
        return IDENTITY_B6(ABSTAIN_UNRESOLVED_CONFLICT)

    return proposal as B6DecisionEvidence with memory_status FUSED
```

当 pass 0 recommended 但 Controller 因预算/工具不可用未执行任何核验时，逻辑上视为 unresolved，直接本地 abstain；不能把原 proposal 提交为 fused。

### 10.6 B6 后置条件

```text
e_commit = reliability_commit*d_commit
u_commit = 1-abs(e_commit)
abs(e_commit)<=reliability_commit
reobserve_pass_count in {0,1}
```

每窗口只有最终一次 `B6DecisionEvidence` accepted。Pass 0 的 pending proposal 只在 trace/event 中保留，不能进入 B4。

## 11. B4 Sticky Temporal Belief

### 11.1 算法 T0：Clock Channel Inputs

B4 物理时钟只读取最终 accepted B2 packets/modality evidence：

```text
for channel m:
    coverage_t_m = union of original observed_intervals from
                   accepted packets contributing to ModalityEvidence_t_m
    h_t_m = MEASURE(coverage_t_m)
    overlap_t_m = COVERAGE_OVERLAP_RATIO(
        coverage_t_m, previous accepted coverage for same channel)
    h_new_t_m = max(delta_t, h_t_m*(1-overlap_t_m))

    kappa_clock_t_m = 0
    a_t_m = q_t_m*(1-kappa_clock_t_m)*abs(d_t_m)
          = abs(P_t_m-N_t_m)
```

`kappa_clock_m=0` 是 B2 接口的确定性实例化：同通道正负冲突已经由 `d_m=(P_m-N_m)/q_m` 净化，Schema v1 没有第二个独立 per-channel conflict；再次折扣会重复计算。跨来源族 conflict 已进入最终 local/commit evidence，但不会把历史 case 伪装成新增观察时长。

使用 original observed intervals 而非 clip 到目标窗口后的覆盖，才能识别“每 0.5 秒重复观察一个 10 秒 clip”只新增 0.5 秒信息。

### 11.2 算法 T1：Elastic Dual Clock

固定数值保护常数：

```text
EPS_CLOCK = 2^-52
```

```text
ALGORITHM UPDATE_CLOCKS(B2,previous_clock_state,boundary):
    delta = WindowInput.delta_us
    compute h_new_m and a_m for canonical channel order
    A_sum = ordered_sum(a_m)

    if A_sum==0:
        H = delta
    else:
        H = ordered_sum(a_m*h_new_m)/(A_sum+EPS_CLOCK)

    tau_f = max(delta,H)
    scene_age = (1-boundary)*(previous.scene_age+delta)

    D = protocol-readable completed scene durations
    T_scene = MEDIAN(D union {max(scene_age,H)})
    tau_s = max(tau_f,T_scene)

    alpha_f = exp(-delta/tau_f)
    alpha_s = exp(-delta/tau_s)
    ONE_BELOW_ONE = 1-2^-53
    alpha_f = min(alpha_f,ONE_BELOW_ONE)
    alpha_s = min(alpha_s,ONE_BELOW_ONE)
    rho_f = alpha_f*(1-boundary)
    rho_s = alpha_s*(1-boundary)
    require 0<=rho_f<=rho_s<1
    RETURN all clock values
```

Median 对奇数集合取中值；偶数集合取两个中间值的算术平均。当前主线 `boundary=0`、`D=empty`：

```text
scene_age_t = scene_age_(t-1)+delta
T_scene=max(scene_age,H)
tau_s=max(tau_f,scene_age)
```

### 11.3 算法 T2：Fast/Slow 更新

```text
ALGORITHM UPDATE_MOMENTUM(commit,clock,previous):
    validate e=reliability*d and u=1-abs(e)
    valid_observation = STRICT_GT(reliability,0)

    if (not previous.has_valid_observation and valid_observation)
       or NUMERIC_EQ(clock.boundary,1):
        F=e
        S=e
    else:
        F=rho_f*previous.F + (1-rho_f)*e
        S=rho_s*previous.S + (1-rho_s)*e

    has_valid = previous.has_valid_observation or valid_observation
    S_prior = rho_s*previous.S
    novelty = abs(e-S_prior)/2
    w = reliability*novelty
    M = w*F+(1-w)*S

    require F,S,M in [-1,1]
    RETURN F,S,M,has_valid,S_prior,novelty,w
```

连续缺失时 reliability=0、e=0，只衰减历史并趋向未知，不能产生负方向。首个可靠但方向为 0 的观察初始化 `F=S=0` 并建立 valid context；后续按普通递推。

### 11.4 算法 T3：连续分数与时序不确定性

```text
z = (M+1)/2
u_commit = 1-reliability*abs(d)
g = abs(F-S)/2
g_uncertain = (1-reliability)*g
U = 1-(1-u_commit)*(1-g_uncertain)
lower = min(1,max(0,z-U/2))
upper = min(1,max(0,z+U/2))
```

```text
ConfidentAbnormal = CMP(lower,0.5)==+1
ConfidentNormal   = CMP(upper,0.5)==-1
PositiveUncertain =
    CMP(lower,0.5)<=0 AND CMP(upper,0.5)>=0 AND CMP(z,0.5)==+1
```

`[lower,upper]` 只是操作状态带，不是统计置信区间。

### 11.5 算法 T4：Hysteresis

```text
NEXT_STATE(previous, CA, CN, PU):
    switch previous:
      NORMAL:
        if CA: ABNORMAL
        else if PU: SUSPICIOUS
        else: NORMAL

      SUSPICIOUS:
        if CA: ABNORMAL
        else if CN: NORMAL
        else: SUSPICIOUS

      ABNORMAL:
        if CN: RECOVERING
        else: ABNORMAL

      RECOVERING:
        if CA: ABNORMAL
        else if CN: NORMAL
        else: RECOVERING
```

Transition reason 固定为 `CONFIDENT_ABNORMAL | CONFIDENT_NORMAL | POSITIVE_UNCERTAIN | HOLD_UNCERTAIN | HOLD_DEFAULT` 中与分支匹配的一项。

### 11.6 算法 T5：B4 exactly-once commit

```text
ALGORITHM COMMIT_B4(window,final_B2,final_B6,previous_state):
    require no accepted B4Decision for window
    require final B6 parent hash accepted
    require previous state version matches window ordinal

    clock = T1(final B2 physical coverage only)
    momentum = T2(final B6 scalar tuple,clock,previous)
    z,U,band = T3(momentum,final B6)
    state = T4(previous.state,band predicates)

    construct complete MomentumTrace
    construct B4Decision with version before/after+1
    atomically append decision event and immutable artifact
    mark window B4_COMMITTED
    RETURN decision and new B4 state
```

Hysteresis 只能读 z/U，不能修改 z、F、S、M 或 B6。B4 之后禁止 Gaussian。

## 12. 每窗口端到端参考控制流

### 12.1 算法 W0：RUN_WINDOW

```text
ALGORITHM RUN_WINDOW(window):
    ACCEPT WindowInput and base visual observation
    base_B2 = BUILD_B2_OUTPUT(base packets)

    if entry supports tools:
        B2_pass0 = RUN_CONTROLLER_PASS(0,base_B2,no request)
    else:
        B2_pass0 = explicit entry adapter output

    manifest0,bundle0 = RETRIEVE(B2_pass0,READABLE_MEMORY(...))
    b6_0 = RUN_B6(B2_pass0,manifest0,bundle0,pass_count=0)

    if b6_0 is PENDING_REOBSERVATION:
        request = direction-free EvidenceRequest
        controller_result = RUN_CONTROLLER_PASS(1,B2_pass0,request)

        if no action authorized/executed:
            final_B2 = B2_pass0
            final_B6 = IDENTITY_B6(ABSTAIN_UNRESOLVED_CONFLICT)
        else:
            B2_pass1 = rebuild from accepted current-window evidence,
                       replacing/superseding same action observations by pass rules
            manifest1,bundle1 = RETRIEVE(B2_pass1,READABLE_MEMORY(...))
            final_B2 = B2_pass1
            final_B6 = RUN_B6(B2_pass1,manifest1,bundle1,pass_count=1)
    else:
        final_B2 = B2_pass0
        final_B6 = b6_0

    require one final B6 commit
    decision = COMMIT_B4(window,final_B2,final_B6,previous_B4_state)
    freeze WindowArtifact
    RETURN WindowArtifact
```

### 12.2 Pass 1 证据替换规则

- Pass 1 的新 packet 与 pass 0 packet 都保留在 audit。
- 对相同 `action_key/channel_id`，pass 1 packet 是 final B2 的当前核验观察，pass 0 同 action packet不再参与 final channel envelope；否则重复核验会获得额外票。
- Pass 1 未重新调用的 channel 继承 pass 0 accepted packet。
- 该 supersession map 必须写入 pass 1 B2 derivation trace，并按 action key 排序。
- 失败的 pass 1 replacement 不删除成功的 pass 0 observation；该 channel 保留 pass 0，失败另记 audit。B6 因 unresolved conflict 最终本地 abstain。

这保证“核验”是替换/更新当前观察，而不是把同源重复加入证据池。

## 13. Message、Event 与 exactly-once 参考算法

### 13.1 算法 X0：接受不可变消息

```text
ALGORITHM ACCEPT_MESSAGE(envelope):
    validate exact versions, schema, permissions and causal phase
    recompute payload_hash, input_hash, message_id
    K = (run,video,window,pass,producer,payload_type)

    existing = message ledger lookup(K)
    if existing exists:
        if existing.payload_hash == envelope.payload_hash:
            return existing result as DUPLICATE_IDENTICAL_MESSAGE
        else:
            FAIL CONFLICTING_REPLAY

    verify every parent exists, is accepted and hash matches
    atomically append accepted event/artifact and ledger K
    RETURN accepted object
```

Ledger 可以是数据库派生索引，但 event/artifact 是可重建事实来源。

### 13.2 算法 X1：工具调用 write-ahead

```text
ALGORITHM EXECUTE_TOOL_EXACTLY_ONCE(plan):
    invocation_id = content ID of run/window/pass/step/action/input hash

    atomically:
        accept ToolPlan
        append BUDGET_DEBIT once
        append TOOL_INVOCATION_STARTED(invocation_id)

    if completed artifact/event already exists:
        return it without calling tool

    call backend with invocation_id/idempotency key when supported
    persist raw output to temporary content-addressed artifact
    verify hash, atomically publish artifact
    append TOOL_EXECUTION_COMPLETED or TOOL_FAILURE
```

恢复时存在 STARTED 但没有完成事件：

```text
if backend supports idempotent result lookup:
    query same invocation_id, never create a new call
else:
    emit TOOL_RESULT_INDETERMINATE
    keep capability UNKNOWN
    mark action used; do not retry in same pass
```

该分支承认外部调用可能已消耗资源，避免为了完整结果重复调用并破坏成本审计。

### 13.3 算法 X2：B4 原子提交

```text
ALGORITHM ATOMIC_B4_COMMIT(decision,expected_state_version):
    lock/compare-and-swap video B4 state version
    require current version == expected_state_version
    require no accepted decision for window ID
    verify B6 parent and decision hash
    atomically:
        append B4_DECISION_COMMITTED
        persist decision artifact
        advance state version by 1
    return committed decision
```

重复同 hash 返回原 decision；不同 hash 是 fatal conflicting duplicate。

### 13.4 算法 X3：Prediction Freeze

```text
ALGORITHM FREEZE_VIDEO_PREDICTIONS(video):
    expected = input manifest ordered window IDs
    actual = committed B4 decisions ordered by window ordinal
    require actual IDs exactly equal expected
    require each decision exactly once and state versions continuous
    persist predictions.json from z/state/interval/hash fields
    compute ordered_decision_hashes and prediction_manifest_hash
    Decision emits PredictionFreezeRecord
    Orchestrator verifies all parent artifacts durable
    append PREDICTION_FROZEN
    mark per-video predictions immutable
```

### 13.5 算法 X4：Write Permit

```text
ALGORITHM ISSUE_WRITE_PERMIT(freeze,candidates,current_snapshot,protocol):
    require protocol == ZS_STREAM_CAUSAL
    verify freeze accepted and current video matches
    eligible = LONG_TERM candidates with final eligible lifecycle revisions
    if eligible is empty:
        append NO_ELIGIBLE_CANDIDATES audit
        return no permit and leave memory version unchanged
    sort candidate IDs ascending
    bind prediction hash, current snapshot/version, IDs and scope
    compute permit ID excluding its own ID/hash field
    append WRITE_PERMIT_ISSUED
    RETURN immutable permit
```

Independent 协议必须在入口拒绝，不允许签出空 permit 伪装合规。

### 13.6 算法 X5：Inference Freeze 与 Evaluator Gate

```text
ALGORITHM FREEZE_RUN_FOR_EVALUATION(run):
    require every intended video has FROZEN status
    require no unresolved fatal failure
    verify all event sequences and hashes
    verify prediction and Memory artifact hashes
    build output_hash_manifest
    update run status to INFERENCE_FROZEN

ALGORITHM START_EVALUATOR(config):
    require run status INFERENCE_FROZEN
    verify output_hash_manifest completely
    open annotation manifest only inside Evaluator boundary
    compute metrics with writes restricted to the frozen Evaluator allowlist:
    evaluation/, metrics/, bootstrap/, comparison_tables/
```

不完整 Independent run 可以保留诊断 artifacts，但不得通过该 gate 进入完整主结果。

## 14. Replay 与恢复

### 14.1 算法 P0：事件链验证

```text
VERIFY_EVENT_STREAM(file):
    expected_sequence=0
    seen_idempotency={}
    for line in file order:
        strict UTF-8 and canonical JSON validation
        require sequence==expected_sequence
        recompute payload/event hashes
        verify parent event/message IDs precede or are valid external parents
        if idempotency key repeated:
            require identical payload and no second state effect
        expected_sequence += 1
    return final cursor and file hash
```

### 14.2 算法 P1：Memory 重放

```text
REPLAY_MEMORY(snapshot,event_stream):
    verify snapshot hash/case set/version/cursor
    state = snapshot immutable case set
    for event after cursor:
        if rejected/duplicate audit: no state change
        if SESSION event: rebuild only current-video ephemeral view
        if committed CAS:
            require before version==state.version
            apply exact mutations
            require after version=before+1
            verify resulting case/reservoir hash
    rebuild indexes from resulting case cores
    return state
```

### 14.3 算法 P2：Run 恢复

```text
RECOVER_RUN(run_root):
    validate freeze/run manifests
    validate tool/decision/memory event streams
    load highest legal Memory snapshot, replay remainder
    rebuild indexes/caches
    rebuild accepted message/idempotency ledger

    for each logical slot in frozen total order:
        if accepted: use immutable artifact
        else if tool STARTED only: use X1 recovery branch
        else: resume from first missing slot
```

恢复不能改变 stream order、seed、budget、case U 或 previously accepted model artifacts。

## 15. Failure 与 fallback 参考表

本节只给出算法 fallback，不重新定义严重度。每条 failure 必须按文档 1 第 12 节归入精确枚举 `RECOVERABLE | VIDEO_FATAL | RUN_FATAL`；Stream 中的升级规则同样适用。

| 位置 | 条件 | 数值/状态 fallback | 后续允许行为 |
|---|---|---|---|
| B1 | quality unavailable | gate/r=0，context-only | 其他工具继续 |
| B3 | Controller failure | 当前基础 B2 | 不调用 All-Tools |
| B3 | tool failure | UNKNOWN，不产方向 | 同 pass 其他 action 可继续 |
| B3 | budget exhausted | 当前 B2 | STOP，进入 B5/B6/B4 |
| B5 | query atoms empty | empty manifest | B6 identity |
| B5 | one view fails | remaining views | 继续 RRF/rerank |
| B5 | reranker fails | full RRF order | 继续 manifest freeze |
| B5 | all views fail | empty manifest | B6 identity |
| B5 | embedding unavailable for Long-Term candidate | nu/W=0 | discard，不占槽 |
| B6 | bundle hash mismatch | local identity | 禁止部分 payload |
| B6 | unresolved conflict/no pass 1 | local abstain | 唯一 B4 commit |
| B4 | all modalities unreliable | e=0，time decay，U 上升 | 状态粘性保持 |
| CAS | stale version | reject old permit | replacement permit + Reservoir-only recompute |
| Replay | same key/same hash | return prior result | 无第二副作用 |
| Replay | same key/different hash | fatal reject | 停止 video/run per protocol |

任何 fallback 都必须写 failure/status，不能把 UNKNOWN 伪装为 NORMAL。

## 16. 关键性质与实现断言

### 16.1 B2 有界与闭合

由 `P,N,Q in [0,1]`、`D=max(A,N)<=Q`：

```text
d in [-1,1]
kappa_dir,kappa_fact,kappa in [0,1]
e=Q(1-kappa)d in [-1,1]
u=1-abs(e) in [0,1]
```

Runtime assertion 必须检查 `e=(A-N)(1-kappa_fact)` 的数值等价。

### 16.2 同源复制幂等

时间片内使用 max，来源族内使用 max：

```text
BUILD_B2(E union exact_duplicates(E)) == BUILD_B2(E)
```

结构 trace 可以记录 duplicate audit，但 channel/family/window 数值不变。

### 16.3 B3 有界终止

每 pass 每 action 最多一次，最多两个 pass：

```text
N_actions_per_window <= 2*size(A_registry)
```

失败也把 action 标记 used，因此不会因失败形成无限循环。

### 16.4 B6 Identity 与有界

空/不可用/拒绝/abstain Memory：

```text
B6 commit == local B2 tuple
```

Fused path：

```text
lambda,r_hat,u_hat in [0,1]
e_hat,d_hat in [-1,1]
abs(e_hat)<=r_hat
```

正负历史对称交换只改变 memory direction 符号，不改变可靠度。

### 16.5 B4 有界与分工

Fast/Slow 是 bounded values 的凸组合，M 是 F/S 的凸组合：

```text
F,S,M in [-1,1], z in [0,1]
```

Hysteresis 的输入只有 z/U/previous state，输出只有新 state/reason。实现必须断言 Hysteresis 前后的 z hash 相同。

### 16.6 Causal 与自检索防火墙

对任一当前 query：

```text
readable Session close ordinal < current visible ordinal
readable Long-Term source stream position < current position
current video Long-Term candidate not in readable snapshot
```

任一违反为 causal fatal，不允许过滤后继续主结果。

### 16.7 Reservoir 容量与角色保障

```text
size(M)<=K
if eligible Salient count>=floor(K/2): retained Salient>=floor(K/2)
if eligible Reference count>=floor(K/2): retained Reference>=floor(K/2)
```

这里 eligible count 指当前可维护流中达到保障所需并未因更高同角色 key 淘汰的候选；实现不需要保存无界历史集合。

### 16.8 Predict-before-write

任何成功 LONG_TERM MemoryWriteEvent 必须能沿 parent/hash 链追溯：

```text
MemoryWriteEvent
<- WritePermit
<- PredictionFreezeRecord
<- complete ordered B4Decision set
```

缺任一父对象时成功写入数必须为 0。

## 17. 参考复杂度与资源上界

| 阶段 | 参考复杂度 | 固定上界/说明 |
|---|---|---|
| B2 interval partition | `O(n log n)` | n 为同 channel 区间数 |
| B2 envelopes/family | `O(E+G)` | 主线 G=2 |
| B2 residual conflict | worst `O(E^2)` | 必须先按时间/实体/关系筛 eligible pairs |
| B3 | `O(2*\|A\|^2)` 朴素扫描 | action 次数最多 `2\|A\|`；可用索引优化 |
| Episode summary | `O(T+E)` | T 为 Episode windows |
| Novelty admission | `O(K*d)` | 主线 K=512；d embedding dimension |
| Reservoir repartition | `O(K log K)` 参考实现 | 可用 heaps 优化但结果必须相同 |
| Dense/BM25/Temporal recall | index-dependent | 每 view 只向 RRF 交 B_ret |
| Reranker | `<=3*k_ret` pairs | 主线最多 15 pairs/query |
| B6 | `O(k_ret)` | 主线最多 5 cases |
| B4 | `O(number_of_channels)` | Memory case 数不进入 clock |

实际 token、延迟、显存、GPU/CPU time、reranker pairs 和 Memory bytes 必须作为 B9 audit，不能反馈改变算法。

## 18. 最小参考序列

这些序列不是完整测试矩阵，只定义实现者可手算的 sanity behavior。

### 18.1 B2 duplicate

```text
one VALID packet assessment: r=0.8,d=0.5, full-window coverage
P=0.4,N=0,q=0.4,d_channel=1
duplicate same atom any number of times -> same P/N/q/d
```

注意 channel compression 的 `d_channel` 不等于 atom d；它与 q 共同保持净证据 `q*d=P-N=0.4`。

### 18.2 B6 empty

```text
B2: r_local=0.6,d=0.5 -> e=0.3,u=0.7
top-k empty
B6: e_commit=0.3,reliability=0.6,d=0.5,u=0.7
```

### 18.3 B4 first valid then missing

```text
first valid e=0.6 -> F=S=0.6
next missing e=0,reliability=0 -> F/S decay toward 0
missing does not inject negative evidence
state cannot jump ABNORMAL directly to NORMAL from missing alone
```

### 18.4 Hysteresis isolation

给定同一 F/S/M/U trace，Hysteresis enabled/disabled 的 `z=(M+1)/2` 必须相同。只有 state/event metrics 可以变化。

### 18.5 Permit replay

同一 permit 第一次成功使 memory version `v->v+1`；重复 1 次或 100 次都返回同一 event/snapshot，最终仍为 `v+1`。

## 19. Theory Check Record

| 参考算法 | 理论来源 | 必须保持的理论结论 |
|---|---|---|
| R0-R3 | B0 7.1-7.9；B8 15.1-15.10 | 三协议隔离、因果可见、predict-before-write |
| Q0 | B1；B2 9.2 | Q_in/Q_src 可审计，缺失 fail closed |
| E0-E4 | B2 9.1-9.20 | 双层事实、one-channel、max/Noisy-OR、q/d/kappa 闭合 |
| G0-G3 | B3 10.1-10.10 | 缺口词典序、固定成本、最多两 pass、无方向控制 |
| M0-M5 | B5 12.1-12.10 | State-Delimited、当前 B2 重算、写防火墙 |
| A0-A3 | B5 12.11-12.14 | R*novelty、weighted reservoir、角色保障共享溢出 |
| S0-S6 | B5 12.15-12.17；B8 15.3 | observation-only hybrid retrieval、top-k 后解锁 |
| F0-F4 | B6 13.1-13.11 | rank signed mass、有界融合、冲突 abstain、一次再观察 |
| T0-T5 | B4 11.3-11.14 | Fast/Slow、Elastic Clock、b=0、Hysteresis 不改 z |
| W0 | B3/B5/B6/B4 顺序；B8 15.2 | 只有合法反馈链，B4 exactly once |
| X0-X5/P0-P2 | B8 15.5-15.10；B9 16.22-16.24 | immutable replay、CAS、冻结后评估 |

### 19.1 工程细化审查

本文为消除实现歧义固定了以下细节：

1. 区间 overlap 使用“交集时长/当前覆盖时长”；事实 conflict 的时间系数使用 overlap coefficient。
2. Reference medoid 使用归一化 embedding 的 cosine distance，hash 破平局。
3. Reservoir U 使用 SHA-256 到开区间的可移植映射；候选按 ID 顺序处理。
4. 完全重复以 canonical RetrievalKey serialization hash 和 vector hash 定义。
5. `kappa_clock_m=0`，因为 ModalityEvidence 的 d 已净化同通道正负支持；该选择避免重复折扣。
6. Pass 1 相同 action/channel 的成功核验替换 pass 0 投票；失败核验保留 pass 0 并导致冲突 abstain。
7. 工具调用使用 write-ahead invocation event；无法恢复 started 调用时 fail closed 为 UNKNOWN，不隐式重调。
8. Candidate lifecycle 使用 immutable core 与 append-only revision；scope 转换创建新 wrapper。
9. B2 时间包络的投票单位是每次工具观察的唯一 PacketAssessment；atoms 和 JointAssessment 不获得独立票。

上述细化均不使用标签、指标、学习权重或目标数据阈值，不增加 pass、B4 commit 或 Memory 影响路径。

### 19.2 完成结论

参考算法已给出从输入冻结、证据获取、工具控制、Memory 读写、有界融合、Sticky 决策到 replay/evaluation gate 的单一闭环。实现方案可以改变内部组织，但不得改变本文算法的输入可见性、运算顺序、分支、tie-break、状态副作用和失败 fallback。
