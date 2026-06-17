# Entrypoints And Script Map

下面这张图用于快速理解当前项目的统一入口、实验工作流、资源准备脚本和 baseline 评估脚本之间的关系。

```mermaid
flowchart TD
    A["agentic_vad.py\n统一入口"] --> B["默认无子命令\n进入 REPL"]
    A --> C["doctor\n检查环境/路径/数据就绪"]
    A --> D["run mini / run full / run stage\n统一实验入口"]
    A --> E["assets download\n资源下载入口"]
    A --> F["dataset build-mini\n构建 mini 子集"]
    A --> G["results show\n读取结果摘要"]

    B --> B1["src/app/repl_shell.py\nREPL 命令路由"]
    B1 --> C
    B1 --> D
    B1 --> E
    B1 --> F
    B1 --> G

    C --> C1["src/app/cli.py\ndoctor 命令定义"]
    C1 --> C2["src/app/orchestrator.py\ndoctor 路由"]
    C2 --> C3["src/app/status.py\n路径/依赖/数据检查"]

    D --> D1["src/app/cli.py\n构造 RunRequest"]
    D1 --> D2["src/app/orchestrator.py\nrun(request)"]
    D2 --> D3["src/pipelines/run_agentic_workflow.py\n完整工作流编排"]

    D3 --> P1["pipeline\nsrc/pipelines/run_agentic_vad.py"]
    D3 --> P2["promote\nsrc/pipelines/promote_case_memory.py"]
    D3 --> P3["patterns\nsrc/pipelines/extract_patterns_offline.py"]
    D3 --> P4["metrics\nsrc/eval/agentic_vad_metrics.py"]
    D3 --> P5["compare\n生成 comparison_report.json"]

    P1 --> A1["PerceptionAgent\nsrc/agents/perception_agent.py"]
    P1 --> A2["StoryMemoryAgent\nsrc/agents/story_memory_agent.py"]

    A1 --> T1["VLMTool\ncaption 或 VideoLLaMA3"]
    A1 --> T2["AudioTool\n可选音频"]
    A1 --> T3["OCRTool\n可选 OCR"]
    A1 --> T4["ScoreTool\n首轮打分"]

    A2 --> M1["RAGTool\n检索 case/pattern/session"]
    A2 --> M2["MemoryPolicy\n决定是否写记忆"]
    A2 --> M3["CaseMemoryStore / PatternMemoryStore / SessionMemoryStore"]

    E --> E1["scripts/download_agentic_assets.py\n模型下载/手动资源目录准备"]
    F --> F1["scripts/build_ucf_crime_mini_subset.py\n从 full 数据裁 mini"]
    G --> G1["src/app/results.py\n读取 workflow_summary / comparison_report"]

    H["原始 baseline 脚本"] --> H1["scripts/query_llm_vad.sh\n原始第一轮打分"]
    H --> H2["scripts/refine_score.sh\n原始 refined score"]
    H --> H3["scripts/eval_ucf.sh\n原始 UCF 指标评估"]
```

## Quick Start

- `python agentic_vad.py`
  - 进入 REPL，适合交互式检查、资源准备和实验触发
- `python agentic_vad.py doctor ...`
  - 检查当前数据路径、依赖和输出目录是否就绪
- `python agentic_vad.py run mini ...`
  - 跑一轮 mini 实验
- `python agentic_vad.py run stage pipeline ...`
  - 只跑 pipeline，适合 smoke test
- `python agentic_vad.py results show`
  - 查看最近一次工作流和 compare 结果

