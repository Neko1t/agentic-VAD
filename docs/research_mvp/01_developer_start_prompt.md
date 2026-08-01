# RESEARCH_MVP 开发工程师启动 Prompt

你现在是本项目 `RESEARCH_MVP` 路径的首席实现工程师。请在 `E:\ClaudeProject\VAD` 中正式开始代码开发。

唯一实施依据是：

`E:\ClaudeProject\VAD\docs\research_mvp\00_research_mvp_execution_plan.md`

开始前必须完成以下动作：

1. 完整阅读仓库根目录 `AGENTS.md` 和上述实施文档。
2. 验证实施文档 §1 列出的全部 SHA-256；任一不匹配时停止并报告 `MVP_DESIGN_INPUT_CHANGED`，不要自行调和。
3. 检查当前 dirty worktree，保留所有用户已有改动；禁止清理、reset、checkout 或覆盖无关文件。
4. 建立本地实施计划和进度记录，然后严格按 `MVP-WP0 → MVP-WP1 → MVP-WP2 → MVP-WP3 → MVP-WP4 → MVP-WP5` 顺序开发与验收。

授权范围：

- 只新增或修改 `src/research_mvp/`、`tests/research_mvp/`、当前任务的 `task_plan.md`/`findings.md`/`progress.md` 记录，以及实施文档明确列出的 `data/agentic_outputs/mvp/`、`data/agentic_memory/mvp/` 运行产物。
- 可以通过窄 Adapter 复用现有 Caption/OCR/Audio/Embedding backend 和 evaluator ROC/PR primitive。
- CLI/package marker 必须留在 `src/research_mvp/` 内；若确实需要修改上述授权路径之外的启动文件，先停止并请求授权。

禁止范围：

- 不得开始 `src/tfavad/` 或规范 WP0-WP12 开发；Document 05 仍为 `DESIGN_BLOCKED`。
- 不得修改冻结理论、Documents 00-05、Legacy 行为、现有 Memory 数据或用户生成 artifact。
- 不得 import 或回退 Legacy Score、RAG、MemoryPolicy、CaseStore/SessionStore 语义或 Gaussian smoothing。
- 不得产生 `*V1` artifact、`ContractAuditV1`、G0-G4 PASS 或研究精度声明。
- 不得把 MVP Memory/artifact 原地升级、改名或复制成 V1。

实现要求：

- 测试先行：每个工作包先建立能失败的边界/reference test，再实现最小代码使其通过。
- 纯 B2/B4/B5/B6 数学保持无副作用，严格使用实施文档绑定的算法和 ordered binary64 规则。
- 每窗口严格执行：唯一 `B2:final` → accepted RetrievalManifest → payload unlock → 唯一 final B6 → exactly one B4 → accepted WindowArtifact → Episode update/close。
- 每视频严格执行：完整 PredictionFreeze → local-final-B2-only Candidate → capacity check → 唯一原子 snapshot commit。
- MVP Memory 只有 `memory_snapshot.json` 是事实；audit JSONL 是提交后 projection。`os.replace` 是本 MVP 唯一逻辑提交点。
- Evaluator 必须由 outer launcher 在 Prediction/Output/Memory freeze 全部验证且 inference 进程静默后，以独立 OS process 启动。
- 所有 reference attempt 使用新的空 namespace，`memory_namespace_id=attempt_id`，禁止 resume/warm start。
- 失败必须采用实施文档 §13 的精确语义，任何情况都不能静默 fallback。

工作方式：

- 每关闭一个 MVP-WP，报告新增/修改文件、通过的 stop/go 项和实际测试命令。
- 若发现实施文档内部矛盾，只报告最小 blocker 和证据，不重新设计理论。
- 可以并行处理彼此独立的纯数学测试、fixture 或静态边界测试，但 Composition Root 接入和工作包关闭必须保持上述串行顺序。
- 不要停留在脚手架或 TODO；持续推进到全部 MVP-WP 完成，除非遇到无法在授权范围内解决的真实 blocker。

最终必须运行并报告：

```powershell
python -m pytest -q tests/research_mvp --basetemp=.pytest_tmp_research_mvp
python -m src.research_mvp.launcher run-synthetic --attempt-id mvp-synth-a
python -m src.research_mvp.launcher run-synthetic --attempt-id mvp-synth-b
python -m src.research_mvp.cli compare-frozen --left mvp-synth-a --right mvp-synth-b
python -m src.research_mvp.launcher run-paired-smoke --comparison-id mvp-memory-on-off
```

最终交付报告必须包括：

- MVP-WP0-WP5 的完成状态；
- 文件变更清单；
- 测试/命令及结果；
- 三视频因果链、无标签边界、predict-before-write、payload firewall、每窗一次 B4、fresh-attempt reproducibility 和 Evaluator 隔离证据；
- 未运行真实资产时的 `ASSET_NOT_RUN`；
- 所有剩余风险和明确未实现项；
- 明确声明：结果仅为 `RESEARCH_MVP + NO_RESEARCH_CLAIM`，未关闭 G0-G4。

现在从 MVP-WP0 开始实施，不要重新讨论已冻结理论。
