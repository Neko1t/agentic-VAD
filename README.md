# A Unified Reasoning Framework for Holistic Zero-Shot Video Anomaly Analysis

![FIGURE1](./assets/image.png)

 > [Project Page](https://rathgrith.github.io/Unified_Frame_VAA/)


## Overview

This is the code implementation for the paper [A Unified Reasoning Framework for Holistic Zero-Shot Video Anomaly Analysis (NeurIPS 2025)](https://openreview.net/pdf?id=Qla5PqFL0s). We thank the previous work for their excellent [codebase](https://github.com/lucazanella/lavad).

This repository now serves two purposes:

1. Preserve the original URF-HVAA baseline workflow
2. Develop an `agentic-vad` branch of work that restructures temporal video
   anomaly detection into a lightweight multi-agent system

If you are new to this repository, read it as an agentic VAD project first,
and treat the original paper workflow as the baseline path we compare against.

## Quick Start

Fast repository entrypoints:

- `agentic_vad.py`: new unified project entrypoint
- `PROJECT_OVERVIEW.md`: fastest project summary for a new session
- `agent.md`: current engineering handoff and architectural notes
- `docs/scripts_guide.md`: script usage index
- `docs/agentic_vad_workflow.md`: workflow/runtime design
- `docs/original_project_evaluation.md`: baseline evaluation notes

## Current Focus: Agentic VAD

The current active engineering direction is an `agentic-vad` prototype under
`src/pipelines/run_agentic_vad.py` and `src/pipelines/run_agentic_workflow.py`.

Core roles:

- `PerceptionAgent`: local observation extraction and first-pass scoring
- `StoryMemoryAgent`: rolling context, retrieval, calibration, and memory-write
  proposals
- `CaseMemoryStore` / `PatternMemoryStore`: persistent memory components

Current constraints:

- The default runtime still uses precomputed caption JSON files rather than a
  real online VLM backend.
- Real model downloads do not automatically mean the runtime is already wired
  to consume them.
- The workflow already exports original-eval-compatible temporal scores, so it
  can be compared directly with the author baseline using `ROC AUC / PR AUC`.

## Recommended Reading Order

1. `PROJECT_OVERVIEW.md`
2. `agent.md`
3. `docs/scripts_guide.md`
4. `docs/agentic_vad_workflow.md`
5. `docs/original_project_evaluation.md`

## Setup

### Environments

Simply run following commands:

```
conda env create -f environment.yml
conda activate VAA
```

You can also install dependencies directly:

```bash
pip install -r requirements.txt
```

## Agentic Workflow Entry Points

Main shell entrypoints now live under `scripts/`:

- `scripts/run_agentic_workflow.sh`
- `scripts/run_agentic_workflow_ucf_crime.sh`
- `scripts/run_agentic_workflow_xd_violence.sh`
- `scripts/download_agentic_assets.sh`
- `scripts/build_ucf_crime_mini_subset.sh`

Examples:

```bash
./scripts/download_agentic_assets.sh --list --preset bootstrap
./scripts/build_ucf_crime_mini_subset.sh
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --stage metrics --no-use-chroma
```

For a detailed script index, see:

- `docs/scripts_guide.md`
- `docs/run_agentic_workflow_linux.md`

### Unified Project Entry

The repository now also exposes a single Python entrypoint for the ongoing
workflow unification effort:

```bash
python agentic_vad.py doctor --help
python agentic_vad.py run mini --help
python agentic_vad.py results show
```

Current scope of the unified entry:

- `doctor`: check whether the main experiment inputs exist
- `run mini/full/stage`: route into the agentic workflow
- `assets download`: delegate to the asset downloader
- `dataset build-mini`: delegate to the mini subset builder
- `results show`: read persisted workflow/comparison summaries
- root home screen: show a dashboard-style project overview when no subcommand
  is provided

The unified home screen now exists in an initial form. It currently uses a
dashboard-style terminal view, and the code now includes a Textual-capable
home-screen path with refreshable sections, live-progress display, and initial
mini/full run controls behind the same command surface.

### Dataset

We have provided preprocessed annotation files following formats in previous work (thanks to [LAVAD](https://github.com/lucazanella/lavad)) for easier setup, please download them from [Google Drive](https://drive.google.com/file/d/1jULt7PKZDTronu4eqiMwCqteKRjjVlmn/view?usp=sharing). 

Before running the code, make sure you have downloaded the raw videos under ``./data/{dataset_name}/videos`` and run the provided frame extraction script to extract frames to ``./data/{dataset_name}/videos``. The final data should have structures like this.
```
./data/
{dataset_name}/
    annotations/
    videos/
        {video1_basename}.mp4
        {video2_basename}.mp4
        ...
    frames/
        {video1_basename}/
            000001.jpg
            000002.jpg
            ...
        {video2_basename}/
            000001.jpg
            000002.jpg
            ...
        ...
```

For the current agentic workflow, the most important runtime assets are:

- annotations
- precomputed captions
- optional baseline refined scores

Raw videos and extracted frames become necessary when you want to:

- regenerate captions
- rebuild subsets from videos
- integrate a real online VLM backend

## Model Notes

For experiments using `VideoLLaMA3-7B` and `Llama3.1-8B-Instruct`, we
recommend at least one RTX 3090-class GPU.

For Llama3.1-8B-Instruct model, you need to get the model checkpoint from [here](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct/tree/main/original) . The checkpoint file ```consolidated.00.pth``` should have a SHA256="ab33d910f405204e5d388bc3521503584800461dc96808e287821dd451c1edac". (You can also download the file from [here](https://www.modelscope.cn/models/LLM-Research/Meta-Llama-3.1-8B-Instruct/files).) Our code assumes Llama3 repo is placed under ``./libs/``. And the ``.pth`` files for model checkpoints is placed inside the repo as ``./libs/llama/llama3.1-8b``.

That is, we expect model code/files should be organized as:

```
./libs/
    llama/
        llama/
            __init__.py
            ...
        llama3.1-8b/
            consolidated.00.pth
            params.json
            tokenizer.model
            ...
```

## Current Mini-Experiment Pattern

For fast smoke validation:

1. Prepare annotations / captions / baseline scores
2. Build a small UCF-Crime subset
3. Run:

```bash
./scripts/run_agentic_workflow.sh --stage pipeline --stage metrics --stage baseline-metrics --stage compare --no-use-chroma
```

Outputs will be written under:

```text
data/agentic_outputs/
```

## Original Baseline Workflow

We have provided the score/caption files for reproducing main experiments in our paper, e.g., for ucf_crime, you should see:
 - Extracted video clip captions under ``./data/ucf_crime/captions/video_llama3_json_results``
 - First round scores under ``./data/ucf_crime/scores/videollama3``
 - Prompt files used for first round at ``./data/ucf_crime/scores/videollama3/context_prompt.txt`` and ``./data/ucf_crime/scores/videollama3/format_prompt.txt``
 - Extracted suspicious windows and score statistics at ``./data/ucf_crime/scores/videollama3/highest_lowest_intervals.json``.
 - Extracted anomaly tags at ``./data/ucf_crime/scores/videollama3/suspicious_part_phrases.json``
 - Refined scores under ``./data/ucf_crime/refined_scores/videollama3`` with metrics saved in a folder.

Here are steps to run base experiments on the temporal Video Anomaly Detection (VAD) task.

1. Precompute per-16-frame captions, call following function that produces a folder containing captions for videos. This produces the captions under the specified ``output_dir``. It takes roughly ~20 hours on a single 3090. You can skip this step by using provided precomputed caption results in ``./data/{dataset_name}/captions/videollama3_json_results/``.

```
python ./src/video_pre_caption.py --video_folder "./data/{dataset_name}/videos/" --index_file "./data/{dataset_name}/annotations/test.txt" --output_dir "./data/{dataset_name}/captions/{experiment_name}" --interval 10
```

2. After you have the frame captions, you can run first-round scoring with Llama3.1-8B-Instruct by ``bash scripts/query_llm_vad.sh`` Note that you need to adjust the paths to make sure you are using the correct captions generated by certain VLMs. 

3. With the preliminary round-1 scores generated, run sliding windows to locate suspicious segments using ``python ./src/score_filter.py`` (adjust any paths inside the script to match your setup).

4. Then extract anomaly tag lists by running ``python ./src/summarize_window.py``.

> You can skip steps 2-4 by using pre-computed scores from ``./data/ucf_crime/scores/videollama3``.

5. Start score refinement by running ``bash scripts/refine_score.sh``.

6. With the refined scores, you can evaluate them by running ``bash scripts/eval_{dataset_name}.sh``.


## Video Anomaly Localisation
To run VAL task, you need to get the annotation files from a previous [work](https://github.com/xuzero/UCFCrime_BoundingBox_Annotation). We have preprocessed the file to make the frame file naming format consistent with the codebase of [LAVAD](https://github.com/lucazanella/lavad). We have provided them as an additional file called ``Test_annotation_naming_aligned.pkl``. Saved under ``./data/ucf_crime/``.

After you have the tag list extracted, you can run a VAL run by calling script ``python src/val_priors.py``

We have provided localisation results under different prior tags in ``./data/ucf_crime/localisations/``.

## Video Anomaly Understanding

Before running VAU task, you need to get the [HIVAU-70K dataset](https://github.com/pipixin321/HolmesVAU). We use the value under key ``video_summary`` from ``HolmesVAU/HIVAU-70k/raw_annotations/ucf_database_test.json`` and ``HolmesVAU/HIVAU-70k/raw_annotations/xd_database_test.json`` and preprocessed them for easier use. We included the video summaries under ``video_summaries.json`` for each dataset's root file.

Before you start, you may need to run ``python ./src/score_filter.py`` again for refined scores to extract final anomaly score statistics. Which is necessary for score gating.

Optionally, you can draw bounding boxes for the most suspicious clips for some suspicious videos as described in InterTC steps. To do this, you can run the script: ``python src/draw_bboxes.py``, note that you need to adjust the path to have it take the UCF-crime tag list extracted previously and the finalised score statisics.

After that you can run the script to generate textual summaries for videos via ``python src/vau_priors.py``, note that you need to specify the input/output path of the priors/results. We have provided our InterTC experiment outputs along with several baselines under ``./data/{dataset_name}/understanding/``.

Once you are done, you evaluate the traditional metrics via ``python src/compute_bleu.py <ground_truth.json> <predictions.json>``. For evaluating gpt-scores, you can refer to ``gpt_score_eval.py``.


## Bibtex

```
@inproceedings{
lin2025AUR,
title={A Unified Reasoning Framework for Holistic Zero-Shot Video Anomaly Analysis},
author={Dongheng Lin, Mengxue Qu, Kunyang Han, Jianbo Jiao, Xiaojie Jin, Yunchao Wei},
booktitle={The Thirty-ninth Annual Conference on Neural Information Processing Systems},
year={2025},
url={https://openreview.net/forum?id=Qla5PqFL0s}
}

```






