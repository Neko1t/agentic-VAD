# Agentic VAD TUI Unified Entry Design

## 1. Goal

将当前分散在 `scripts/` 和 `src/pipelines/` 中的实验、下载、评估与对比逻辑整合为一个统一的项目入口，提供面向终端的可视化 TUI 体验。

目标效果如下：

- 用户只需记住一个根目录入口命令。
- 系统自动检查环境、模型、数据、实验产物的完成情况。
- 支持预实验、完整实验、单阶段调试三类运行模式。
- 实验过程可视化，能够看到全局阶段进度和细粒度单行动态进度条。
- 结果自动汇总、表格展示、持久化，并与原作者 baseline 结果对比。

本次设计只面向 TUI，不引入 Web UI。

## 2. Design Principles

### 2.1 One entry, many workflows

根目录只暴露一个主入口，例如：

```bash
python agentic_vad.py
```

同时保留子命令式调用能力，例如：

```bash
python agentic_vad.py doctor
python agentic_vad.py run mini
python agentic_vad.py run full
python agentic_vad.py run stage pipeline
python agentic_vad.py results
```

这样既适合交互式使用，也适合 AutoDL、SSH、批处理和调试。

### 2.2 Wrap existing scripts instead of rewriting everything

不推翻当前已有能力，而是统一编排：

- `scripts/download_agentic_assets.py`
- `scripts/build_ucf_crime_mini_subset.py`
- `scripts/run_agentic_workflow.py`
- `src/pipelines/run_agentic_workflow.py`
- `src/eval/agentic_vad_metrics.py`

新的 TUI 系统负责：

- 统一入口
- 状态检测
- 参数装配
- 进度展示
- 结果归档

这样风险更低，也更方便持续演进。

### 2.3 State-driven UX

所有“是否已完成”的判断都不应散落在脚本里，而应抽象为统一状态模型。

TUI 首页不只是展示按钮，而应先展示：

- 环境是否就绪
- 模型是否就绪
- 数据是否就绪
- mini/full 实验是否可运行
- 哪些步骤缺失
- 如何修复

### 2.4 Progress is a first-class feature

进度条不是装饰，而是系统的一部分。所有主要组件都应能向统一的进度总线发送事件，包括：

- 资产下载
- mini 数据集构建
- pipeline 主流程
- VLM 调用
- score 计算
- story-memory 归纳
- metrics 评估
- baseline 对比

### 2.5 Persistent results by default

每次运行结束后，都必须生成结构化产物，而不是只在终端打印结果。

## 3. User-Facing Experience

### 3.1 Entry modes

统一入口支持两类模式。

#### A. Interactive TUI mode

```bash
python agentic_vad.py
```

进入一个终端界面，展示：

- 项目状态面板
- 缺失项提示
- 实验入口
- 最近一次结果摘要
- 常用维护操作

#### B. Direct command mode

```bash
python agentic_vad.py doctor
python agentic_vad.py assets download --preset models-core
python agentic_vad.py dataset build-mini
python agentic_vad.py run mini
python agentic_vad.py run full
python agentic_vad.py run stage pipeline
python agentic_vad.py results show
```

这样既能给共享用户提供低门槛入口，也能给开发者提供稳定的调试方式。

### 3.2 Home screen layout

TUI 首页建议由五个区域组成：

1. `Project Status`
   - Python / Conda / Torch / CUDA
   - 模型状态
   - 数据状态
   - 输出状态

2. `Required Actions`
   - 缺失项清单
   - 修复建议

3. `Experiments`
   - 运行预实验
   - 运行完整实验
   - 单阶段运行
   - 恢复最近一次运行

4. `Recent Results`
   - 最近一次实验的 Agentic 与 Baseline 指标
   - 输出路径

5. `Utilities`
   - 下载资产
   - 构建 mini 子集
   - 仅评估
   - 仅 compare
   - 导出报告

### 3.3 Operating philosophy

TUI 应优先告诉用户“当前还差什么”，而不是让用户猜该先执行哪个脚本。

因此交互顺序应是：

1. 启动系统
2. 自动自检
3. 显示缺失项和建议操作
4. 用户选择预实验或完整实验
5. 系统执行并展示进度
6. 系统展示结果并保存报告

## 4. Architecture

建议新增统一应用层：

```text
agentic_vad.py
src/
  app/
    __init__.py
    cli.py
    tui_app.py
    orchestrator.py
    workflows.py
    status.py
    models.py
    reporting.py
    results.py
```

### 4.1 `agentic_vad.py`

根目录唯一主入口。

职责：

- 无参数时进入 TUI。
- 有参数时分发到 CLI 子命令。

### 4.2 `src/app/cli.py`

命令行子命令层，建议使用 `typer`。

职责：

- 解析 `doctor / assets / dataset / run / results` 等命令。
- 将参数交给 orchestrator。

### 4.3 `src/app/tui_app.py`

交互式终端界面，建议使用 `textual`。

职责：

- 首页布局
- 状态刷新
- 菜单交互
- 进度区域
- 日志区域
- 结果区域

### 4.4 `src/app/orchestrator.py`

统一流程调度层，是整个整合方案的核心。

职责：

- 接收用户操作或 CLI 请求
- 调用状态检查器
- 选择对应 workflow
- 组织 stage 顺序
- 分发进度事件
- 捕获错误并生成结构化结果

### 4.5 `src/app/workflows.py`

预设工作流定义层。

建议内置：

- `mini_experiment_workflow`
- `full_experiment_workflow`
- `single_stage_workflow`
- `doctor_workflow`

每个 workflow 只定义“跑哪些 stage、使用哪些路径、允许哪些跳过策略”，不直接处理底层业务。

### 4.6 `src/app/status.py`

状态检测中心。

职责：

- 环境检查
- 资产检查
- 数据检查
- 输出与 baseline 检查
- 形成统一状态对象

### 4.7 `src/app/models.py`

统一 schema 定义。

建议包含：

- `CheckStatus`
- `ProjectStatusSnapshot`
- `RunRequest`
- `RunStageResult`
- `RunSummary`
- `ComparisonRow`

### 4.8 `src/app/reporting.py`

结果汇总与持久化。

职责：

- 生成 markdown 报告
- 生成 csv/json 结果
- 生成终端表格
- 生成图像摘要

### 4.9 `src/app/results.py`

历史结果读取与展示。

职责：

- 读取最近运行结果
- 汇总历史运行
- 为 TUI 首页和 `results show` 提供数据

## 5. State Detection Model

统一状态系统应覆盖以下检查器。

### 5.1 Environment checker

检查：

- Python 版本
- 当前 Conda 环境
- `torch` 是否可导入
- CUDA 是否可用
- 必需 Python 包是否存在

### 5.2 Asset checker

检查：

- embedding 模型目录
- VLM 模型目录
- LLM 模型目录
- `.asset_status/*.done` 标记
- 对应模型目录是否完整

规则：

- 不能仅依赖目录存在。
- 对于自动下载资产，优先使用显式完成标记。
- 对于手动上传资产，允许通过路径规则和结构校验认定完成。

### 5.3 Dataset checker

检查：

- `data/ucf_crime/annotations`
- `data/ucf_crime/captions`
- `data/ucf_crime/refined_scores`
- `data/ucf_crime/videos`
- `data/ucf_crime/frames`
- `data/ucf_crime_mini/...`

应区分：

- 可运行预实验
- 可运行完整实验
- 仅可运行评估

### 5.4 Experiment artifact checker

检查：

- 既有输出目录
- 已完成的 stage
- 是否存在 metrics 结果
- 是否存在 baseline compare 结果

### 5.5 Unified output schema

建议统一为：

```python
class CheckStatus(BaseModel):
    name: str
    ready: bool
    level: Literal["ok", "warn", "error"]
    message: str
    fix_hint: str | None = None
```

多个检查项再组合为 `ProjectStatusSnapshot`。

## 6. Workflow Design

### 6.1 Standard stages

统一定义以下 stage：

- `doctor`
- `assets`
- `dataset`
- `pipeline`
- `metrics`
- `baseline-metrics`
- `compare`
- `report`

### 6.2 Mini experiment

数据根路径指向 `data/ucf_crime_mini/`。

用途：

- 快速检查系统能否跑通
- 验证模型和 pipeline 是否正常接线
- 快速对比 Agentic 与 Baseline 的趋势

### 6.3 Full experiment

数据根路径指向 `data/ucf_crime/`。

用途：

- 正式实验
- 论文级评估
- 与原作者方案完整对齐

### 6.4 Single-stage execution

允许单独运行某个 stage，例如：

```bash
python agentic_vad.py run stage pipeline
python agentic_vad.py run stage metrics
python agentic_vad.py run stage compare
```

用途：

- 调试
- 断点续跑
- 快速检查单一模块

### 6.5 Resume behavior

如果输出目录中存在已完成 stage 的产物，应支持：

- 自动跳过已完成部分
- 或通过 `--force` 重新执行

这部分的判断规则应依赖 manifest 或 stage 完成标记，而不是只靠目录存在。

## 7. Progress Visualization Design

### 7.1 Two-level progress

建议实现两层进度：

#### A. Global stage progress

展示整个实验跑到哪一步，例如：

- `[1/6] pipeline`
- `[2/6] metrics`
- `[3/6] baseline-metrics`

#### B. In-stage progress

展示当前 stage 内的细粒度进度，例如：

- 当前视频
- 当前窗口
- VLM 调用计数
- perception agent 计数
- story-memory 计数
- memory write 计数

### 7.2 Progress event schema

建议统一事件结构：

```python
class ProgressEvent(BaseModel):
    stage: str
    task_id: str
    message: str
    completed: int
    total: int
    status: Literal["pending", "running", "done", "error"]
```

### 7.3 Event producers

以下模块应逐步接入进度事件：

- `scripts/download_agentic_assets.py`
- `scripts/build_ucf_crime_mini_subset.py`
- `src/pipelines/run_agentic_workflow.py`
- `src/tools/vlm_tool.py`
- `src/tools/score_tool.py`
- `src/agents/perception_agent.py`
- `src/agents/story_memory_agent.py`
- `src/eval/agentic_vad_metrics.py`

### 7.4 Rendering strategy

TUI 中建议包含：

- 顶部：全局进度条
- 中部：活跃任务列表，每个任务单行动态刷新
- 底部：日志滚动区

必须避免刷屏式输出，优先单行更新。

## 8. Results and Persistence

### 8.1 Output directory convention

建议统一输出到：

```text
data/agentic_outputs/<dataset>/<run_id>/
```

### 8.2 Standard artifacts

每次运行至少写出：

- `run_config.json`
- `status_summary.json`
- `agentic_metrics.json`
- `baseline_metrics.json`
- `comparison.json`
- `comparison_table.md`
- `comparison_table.csv`
- `summary_report.md`

如条件允许，再补充：

- `plots/roc_pr_summary.png`
- `plots/score_distribution.png`

### 8.3 Comparison table

建议对比表包含：

- Dataset
- Split
- Experiment Type
- Agentic ROC AUC
- Baseline ROC AUC
- Delta ROC AUC
- Agentic PR AUC
- Baseline PR AUC
- Delta PR AUC
- Runtime
- Memory Mode
- Model Config

### 8.4 TUI result presentation

TUI 结束页至少展示：

- 结果摘要
- 对比表格
- 输出目录
- 最近一次实验状态

## 9. Implementation Strategy

建议按四个阶段实施。

### Phase 1: Unified entry and command routing

目标：

- 新增 `agentic_vad.py`
- 新增 `src/app/cli.py`
- 打通 `doctor / assets / dataset / run / results` 基础命令

产出：

- 统一命令入口可用
- 可直接替代当前多数散落脚本入口

### Phase 2: Status system and workflow orchestration

目标：

- 新增状态检测器
- 新增 orchestrator
- 将 mini/full/single-stage 统一编排

产出：

- 系统能够自动判断“还缺什么”
- 系统能够自动决定哪些 stage 可以执行

### Phase 3: TUI interface and progress integration

目标：

- 新增 `textual` TUI 首页
- 接入统一进度总线
- 支持单行动态更新

产出：

- 用户进入后能直观看到整个系统状态与运行进度

### Phase 4: Result center and persistence polish

目标：

- 补齐结果表格、markdown、csv、json 产物
- 整理 compare 展示
- 首页展示最近一次运行摘要

产出：

- 实验结束即可获得可复用、可分享的结果产物

## 10. Testing Strategy

这次改造必须同步建设测试，避免入口整合后出现“能启动但不能用”的情况。

### 10.1 Unit tests

新增测试覆盖：

- 状态检查器
- workflow 路由逻辑
- run request 参数解析
- result/report 生成
- stage 跳过与恢复判断

### 10.2 Integration tests

使用小型伪数据或 mini 数据集覆盖：

- `doctor`
- `run mini`
- `run stage pipeline`
- `results show`

### 10.3 Contract tests

确保以下 contract 稳定：

- status schema
- progress event schema
- orchestrator 输出 schema
- compare 报告 schema

### 10.4 Manual verification

至少人工验证：

- Windows 本地入口
- Linux/AutoDL 入口
- 无模型时的缺失提示
- 仅有 mini 数据集时的提示逻辑
- 完整流程结束后的表格展示

## 11. Risks and Mitigations

### 11.1 Existing scripts have inconsistent output styles

风险：

- 当前 shell/python/pipeline 输出风格不一，接入 TUI 时会混乱。

缓解：

- 用 orchestrator 统一包装
- 日志和进度事件分离

### 11.2 False-positive completion detection

风险：

- 目录存在但下载未完成，或 stage 被误判为完成。

缓解：

- 继续使用显式 `.done` 标记和 manifest 规则
- 禁止单纯以目录存在作为完成依据

### 11.3 TUI blocking long-running jobs

风险：

- 长流程阻塞界面刷新。

缓解：

- TUI 通过 worker 或后台任务运行 workflow
- 进度通过事件队列回传

### 11.4 Cross-platform path issues

风险：

- 本地 Windows 与 AutoDL Linux 路径规则不同。

缓解：

- 全部使用 `pathlib`
- 避免写死路径分隔符

### 11.5 Metric comparison mismatch

风险：

- Agentic 与 baseline 结果可能使用不同口径输入，导致对比失真。

缓解：

- compare 模块只读取明确对齐的数据源
- 将评估配置写入 `run_config.json`

## 12. Recommendation

推荐采用以下落地顺序：

1. 统一入口
2. 状态检测
3. workflow 编排
4. TUI 首页
5. 进度事件总线
6. 结果中心

原因是这样可以先把系统“收口”，尽快获得稳定可用的统一入口，再逐步增强交互体验与结果展示能力。

## 13. Scope Boundary

本设计当前不包含：

- Web UI
- 远程任务调度平台
- 多用户并发管理
- 复杂数据库后端

这些能力未来可以建立在统一 orchestrator 和结果中心之上，但不应进入本轮范围。
