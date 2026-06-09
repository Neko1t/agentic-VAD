# Original Project Evaluation Notes

## 1. Scope

This note summarizes how the original repository evaluates whether the model
outputs are good or not across its three main task families:

- temporal Video Anomaly Detection (VAD)
- Video Anomaly Localisation (VAL)
- Video Anomaly Understanding (VAU)

The main sources are:

- `README.md`
- `src/eval.py`
- `scripts/eval_*.sh`
- `src/val_priors.py`
- `src/compute_bleu.py`
- `src/gpt_score_eval.py`

## 2. Temporal VAD Evaluation

Main evaluation file:

- `src/eval.py`

Shell entry points:

- `scripts/eval_ucf.sh`
- `scripts/eval_ub.sh`
- `scripts/eval_msad.sh`
- `scripts/eval_xd.sh`

### Input Assumption

The original VAD pipeline produces clip-level anomaly scores in JSON files.
These scores are stored per video under:

```text
./data/{dataset}/scores/.../ or ./data/{dataset}/refined_scores/.../
```

The evaluation code compares those scores against temporal anomaly annotations
for each dataset.

### What `src/eval.py` Does

For each video:

1. load temporal annotations
2. load predicted clip-level scores from JSON
3. smooth scores using `gaussian_filter1d(..., sigma=10)`
4. repeat clip-level scores to frame-level scores using `frame_interval`
5. truncate or pad to match video length
6. flatten scores and labels across all test videos
7. convert labels to binary normal/anomaly labels

### Metrics Used

The main temporal VAD quality metrics are:

- `ROC AUC`
- `PR AUC`

These are computed with:

- `roc_curve`
- `precision_recall_curve`
- `auc`

The code also computes two threshold-selection statistics:

- optimal threshold by `Youden's J`
- optimal threshold by `max F1`

These are not the main ranking metrics, but they are used to understand where a
reasonable operating point lies.

### Output

The evaluator writes:

- `roc_auc.txt`
- `pr_auc.txt`
- `optimal_thresholds.txt`

inside the chosen metrics folder.

### Interpretation

For the original temporal anomaly detection task, "better" means:

- higher `ROC AUC`
- higher `PR AUC`

The code is fundamentally frame-level evaluation after expanding clip scores to
frames.

## 3. VAL Evaluation

Main file:

- `src/val_priors.py`

### Task Idea

VAL is evaluated as suspicious-region localization in frames, using annotated
bounding boxes from UCF-Crime style localization data.

The script uses a visual model to predict a suspicious region and then compares
the predicted box to ground-truth boxes.

### Core Metric

The core localization metric is IoU-based:

- `IoU = intersection over union`

There are two important thresholds in the script:

- `BETA = 0.1`
  IoU threshold for deciding whether a detection is correct
- `CONF_THRESH = 0.5`
  confidence threshold for final detection metrics

### What The Script Computes

For each frame:

1. predict a box and confidence
2. compute raw IoU with ground truth
3. if confidence is below `0.5`, final IoU is forced to `0`
4. store per-frame detection results

Then it aggregates final IoU values and prints:

- `TIoU (conf>=0.5)`

The script also computes per-video average IoU and then averages across videos.

### Interpretation

For localization, "better" means:

- higher final IoU / higher TIoU
- more confident detections that still overlap the ground truth

This is a geometry-based localization quality metric, not a text metric.

## 4. VAU Evaluation With Traditional Text Metrics

Main file:

- `src/compute_bleu.py`

### Task Idea

VAU generates textual descriptions or summaries for videos. The original code
evaluates predicted summaries against ground-truth summaries.

### Metrics Used

The script computes:

- `BLEU-1`
- `BLEU-2`
- `BLEU-3`
- `BLEU-4`
- `BLEU'`
  the script prints this as the sum-style aggregate of BLEU-1 to BLEU-4
- `CIDEr`
- `METEOR`
- `ROUGE-L`

### How It Works

For every matched video key:

1. load ground-truth text
2. load predicted text
3. tokenize reference and hypothesis
4. compute per-sample BLEU, METEOR, ROUGE-L
5. build CIDEr inputs
6. average the metrics across samples

### Interpretation

For textual understanding, "better" means:

- higher BLEU
- higher CIDEr
- higher METEOR
- higher ROUGE-L

These are standard reference-based caption/summary metrics.

## 5. VAU Evaluation With GPT Scores

Main file:

- `src/gpt_score_eval.py`

### Task Idea

The repository also includes an LLM-based judge for generated video summaries.

### Dimensions Used

The script evaluates three dimensions:

- `Reasonability`
- `Detail`
- `Consistency`

Each is scored between `0` and `1` using GPT.

### Process

For each video:

1. load reference description
2. load predicted description
3. prompt GPT separately for each dimension
4. parse a dictionary-style numeric score
5. average scores across videos

### Interpretation

This is a semantic quality evaluation complementing lexical overlap metrics.

For GPT-based understanding evaluation, "better" means:

- higher reasonability
- higher detail
- higher consistency

## 6. What The README Says About Evaluation

The README describes the evaluation process in three layers:

### Temporal VAD

After score refinement:

```text
bash scripts/eval_{dataset_name}.sh
```

This runs `src.eval`.

### VAU

Traditional metrics:

```text
python src/compute_bleu.py <ground_truth.json> <predictions.json>
```

LLM-based metrics:

```text
python src/gpt_score_eval.py ...
```

### VAL

The README mainly explains how to run the localization workflow and where
outputs are stored. The actual implemented metric in code is IoU-based, via
`src/val_priors.py`.

## 7. Bottom Line

The original project judges quality differently depending on the task:

- Temporal VAD:
  frame-level anomaly discrimination quality using `ROC AUC` and `PR AUC`
- VAL:
  suspicious-region localization quality using IoU-style metrics, especially
  `TIoU`
- VAU:
  text generation quality using BLEU, CIDEr, METEOR, ROUGE-L, plus GPT-based
  semantic scores for reasonability, detail, and consistency

So the original authors did not use one universal metric. They used
task-specific evaluation:

- detection uses ranking/discrimination metrics
- localization uses geometry overlap
- understanding uses text similarity and judge-model scores
