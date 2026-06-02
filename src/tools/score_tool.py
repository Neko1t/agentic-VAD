from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from src.core.config import ScoringConfig
from src.core.schemas import CalibrationResult, ObservationCard


class ScoreTool:
    def __init__(self, config: ScoringConfig):
        self.config = config
        self.high_risk_keywords = {
            "fight": 9.0,
            "fall": 8.0,
            "chase": 8.5,
            "run": 6.0,
            "weapon": 9.5,
            "crowd": 6.5,
            "panic": 8.0,
            "grab": 7.0,
            "hit": 8.5,
            "distress_audio": 8.0,
            "alarm": 8.0,
        }
        self.low_risk_keywords = {
            "walk": 2.0,
            "stand": 1.5,
            "normal": 1.0,
            "empty": 1.0,
        }

    def _keyword_score(self, tokens: Iterable[str], default_score: float) -> float:
        found_scores: List[float] = []
        for token in tokens:
            normalized = token.strip().lower()
            if normalized in self.high_risk_keywords:
                found_scores.append(self.high_risk_keywords[normalized])
            elif normalized in self.low_risk_keywords:
                found_scores.append(self.low_risk_keywords[normalized])
        if not found_scores:
            return default_score
        return max(found_scores)

    def _text_score(self, text: str, default_score: float) -> float:
        lowered = text.lower()
        matched: List[float] = []
        for keyword, score in self.high_risk_keywords.items():
            if keyword in lowered:
                matched.append(score)
        for keyword, score in self.low_risk_keywords.items():
            if keyword in lowered:
                matched.append(score)
        if not matched:
            return default_score
        return max(matched)

    def _compute_modality_weights(self, card: ObservationCard) -> Dict[str, float]:
        weighted = {
            "vision": self.config.vision_prior * card.modality_confidence.vision_conf,
            "audio": self.config.audio_prior * card.modality_confidence.audio_conf,
            "ocr": self.config.ocr_prior * card.modality_confidence.ocr_conf,
        }
        total = sum(weighted.values())
        if total == 0.0:
            return {"vision": 1.0, "audio": 0.0, "ocr": 0.0}
        return {name: value / total for name, value in weighted.items()}

    def score_observation(self, card: ObservationCard) -> Dict[str, object]:
        weights = self._compute_modality_weights(card)
        vision_score = max(
            self._keyword_score(card.actions, default_score=3.5),
            self._text_score(card.vision_caption, default_score=3.0),
        )
        audio_score = max(
            self._keyword_score(card.audio_events, default_score=0.0),
            self._text_score(" ".join(card.audio_events), default_score=0.0),
        )
        ocr_score = self._text_score(" ".join(card.ocr_texts), default_score=0.0)
        raw_score = max(vision_score, audio_score, ocr_score)
        weighted_score = (
            vision_score * weights["vision"]
            + audio_score * weights["audio"]
            + ocr_score * weights["ocr"]
        )
        uncertainty = 1.0 - max(weights.values())
        reason_trace = [
            f"vision={vision_score:.2f} weight={weights['vision']:.2f}",
            f"audio={audio_score:.2f} weight={weights['audio']:.2f}",
            f"ocr={ocr_score:.2f} weight={weights['ocr']:.2f}",
        ]
        if card.modality_confidence.ocr_conf < 0.3 and card.ocr_texts:
            reason_trace.append("low-confidence OCR was down-weighted before fusion")
        if card.modality_confidence.audio_conf < 0.3 and card.audio_events:
            reason_trace.append("low-confidence audio was down-weighted before fusion")
        return {
            "score_raw": min(10.0, raw_score),
            "score_weighted": min(10.0, weighted_score),
            "modality_weights": weights,
            "reason_trace": reason_trace,
            "uncertainty": max(0.0, min(1.0, uncertainty)),
        }

    def fuse_scores(
        self,
        score_local: float,
        score_story: float,
        retrieval_confidence: float,
        similar_cases: Sequence[object],
        matched_patterns: Sequence[object],
    ) -> CalibrationResult:
        memory_support = 0.0
        reasons = [f"local evidence score={score_local:.2f}", f"story score={score_story:.2f}"]
        if similar_cases:
            average_case_risk = sum(getattr(case, "risk_score", 0.0) for case in similar_cases) / len(similar_cases)
            memory_support += average_case_risk * retrieval_confidence
            reasons.append(
                f"retrieved {len(similar_cases)} similar cases with confidence={retrieval_confidence:.2f}"
            )
        if matched_patterns:
            average_pattern_risk = sum(getattr(pattern, "risk_level", 0.0) for pattern in matched_patterns) / len(matched_patterns)
            memory_support = max(memory_support, average_pattern_risk * min(1.0, retrieval_confidence + 0.1))
            reasons.append(f"matched {len(matched_patterns)} pattern prototypes")
        score_memory_adjusted = max(score_story, (score_story * 0.6) + (memory_support * 0.4))
        if retrieval_confidence < 0.25:
            score_memory_adjusted = score_story
            reasons.append("retrieval confidence was low, so memory had weak influence")
        final_score = (score_local * 0.5) + (score_story * 0.3) + (score_memory_adjusted * 0.2)
        if score_local >= 8.0 and final_score < score_local - 1.0:
            final_score = score_local - 1.0
            reasons.append("strong local evidence limited excessive score suppression")
        return CalibrationResult(
            score_local=min(10.0, score_local),
            score_story=min(10.0, score_story),
            score_memory_adjusted=min(10.0, score_memory_adjusted),
            final_score=min(10.0, max(0.0, final_score)),
            calibration_reason=reasons,
        )
