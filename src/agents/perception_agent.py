from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Iterable

from src.core.schemas import ModalityConfidence, ObservationCard, ToolCallRecord, WindowInput
from src.tools.audio_tool import AudioTool
from src.tools.ocr_tool import OCRTool
from src.tools.score_tool import ScoreTool
from src.tools.vlm_tool import VLMTool


class PerceptionAgent:
    def __init__(
        self,
        vlm_tool: VLMTool,
        audio_tool: AudioTool,
        ocr_tool: OCRTool,
        score_tool: ScoreTool,
    ):
        self.vlm_tool = vlm_tool
        self.audio_tool = audio_tool
        self.ocr_tool = ocr_tool
        self.score_tool = score_tool

    def process_window(self, window_input: WindowInput) -> ObservationCard:
        vision, vision_trace = self._call_tool(
            tool_name="vlm_describe",
            input_summary=window_input.window_id,
            call=lambda: self.vlm_tool.vlm_describe(window_input),
            fallback={
                "vision_caption": "",
                "entities": [],
                "actions": [],
                "scene_context": "unknown scene",
                "confidence": 0.0,
                "artifact_refs": [],
            },
        )
        audio, audio_trace = self._call_tool(
            tool_name="audio_describe",
            input_summary=window_input.window_id,
            call=lambda: self.audio_tool.audio_describe(window_input),
            fallback={"audio_events": [], "transcript": "", "confidence": 0.0},
        )
        ocr, ocr_trace = self._call_tool(
            tool_name="ocr_extract",
            input_summary=window_input.window_id,
            call=lambda: self.ocr_tool.ocr_extract(window_input),
            fallback={"ocr_texts": [], "confidence": 0.0},
        )

        card = ObservationCard(
            video_id=window_input.video_id,
            window_id=window_input.window_id,
            time_span=window_input.time_span,
            vision_caption=str(vision.get("vision_caption", "")),
            entities=list(vision.get("entities", [])),
            actions=list(vision.get("actions", [])),
            scene_context=str(vision.get("scene_context", "")),
            audio_events=list(audio.get("audio_events", [])),
            ocr_texts=list(ocr.get("ocr_texts", [])),
            modality_confidence=ModalityConfidence(
                vision_conf=float(vision.get("confidence", 0.0)),
                audio_conf=float(audio.get("confidence", 0.0)),
                ocr_conf=float(ocr.get("confidence", 0.0)),
            ),
        )
        scored, score_trace = self._call_tool(
            tool_name="score_observation",
            input_summary=f"actions={','.join(card.actions)}",
            call=lambda: self.score_tool.score_observation(card),
            fallback={
                "score_raw": 0.0,
                "score_weighted": 0.0,
                "reason_trace": ["score tool failed; fallback score was used"],
                "uncertainty": 1.0,
            },
        )
        vision_trace = vision_trace.model_copy(
            update={
                "output_summary": str(vision.get("vision_caption", ""))[:300],
                "confidence": float(vision.get("confidence", 0.0)),
                "artifact_refs": self._as_str_list(vision.get("artifact_refs", [])),
            }
        )
        audio_trace = audio_trace.model_copy(
            update={
                "output_summary": ", ".join(str(item) for item in audio.get("audio_events", []))[:300],
                "confidence": float(audio.get("confidence", 0.0)),
            }
        )
        ocr_trace = ocr_trace.model_copy(
            update={
                "output_summary": " | ".join(str(item) for item in ocr.get("ocr_texts", []))[:300],
                "confidence": float(ocr.get("confidence", 0.0)),
            }
        )
        score_trace = score_trace.model_copy(
            update={
                "output_summary": f"weighted={float(scored['score_weighted']):.2f}, raw={float(scored['score_raw']):.2f}",
            }
        )
        return card.model_copy(
            update={
                "score_raw": float(scored["score_raw"]),
                "score_weighted": float(scored["score_weighted"]),
                "reason_trace": list(scored["reason_trace"]),
                "uncertainty": float(scored["uncertainty"]),
                "tool_trace": [vision_trace, audio_trace, ocr_trace, score_trace],
            }
        )

    def _call_tool(
        self,
        tool_name: str,
        input_summary: str,
        call: Callable[[], dict[str, Any]],
        fallback: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        started = time.perf_counter()
        error = None
        try:
            result = call()
        except Exception as exc:
            result = fallback
            error = f"{exc.__class__.__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        return result, self._tool_record(
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary="",
            latency_ms=latency_ms,
            error=error,
        )

    def _tool_record(
        self,
        tool_name: str,
        input_summary: str,
        output_summary: str,
        confidence: float | None = None,
        artifact_refs: Iterable[str] | None = None,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> ToolCallRecord:
        return ToolCallRecord(
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=output_summary[:300],
            confidence=confidence,
            latency_ms=latency_ms,
            error=error,
            artifact_refs=list(artifact_refs or []),
        )

    def _as_str_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, tuple):
            return [str(item) for item in value]
        if value:
            return [str(value)]
        return []
