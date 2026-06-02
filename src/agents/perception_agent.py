from __future__ import annotations

from src.core.schemas import ModalityConfidence, ObservationCard, WindowInput
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
        vision = self.vlm_tool.vlm_describe(window_input)
        audio = self.audio_tool.audio_describe(window_input)
        ocr = self.ocr_tool.ocr_extract(window_input)

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
        scored = self.score_tool.score_observation(card)
        return card.model_copy(
            update={
                "score_raw": float(scored["score_raw"]),
                "score_weighted": float(scored["score_weighted"]),
                "reason_trace": list(scored["reason_trace"]),
                "uncertainty": float(scored["uncertainty"]),
            }
        )
