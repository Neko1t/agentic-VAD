from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.core.schemas import WindowInput


class VLMTool:
    def __init__(
        self,
        captions_dir: Path,
        caption_backend: Optional[Callable[[WindowInput], str]] = None,
    ):
        self.captions_dir = captions_dir
        self.caption_backend = caption_backend

    def _load_caption_map(self, video_id: str) -> Dict[str, str]:
        path = self.captions_dir / f"{video_id}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _select_caption(self, captions: Dict[str, str], window_input: WindowInput) -> str:
        if not captions:
            return ""
        keys = sorted(int(key) for key in captions.keys())
        candidates = [key for key in keys if window_input.time_span.start_frame <= key <= window_input.time_span.end_frame]
        if not candidates and window_input.frame_indices:
            target = window_input.frame_indices[len(window_input.frame_indices) // 2]
            candidates = [min(keys, key=lambda value: abs(value - target))]
        elif not candidates:
            midpoint = (window_input.time_span.start_frame + window_input.time_span.end_frame) // 2
            candidates = [min(keys, key=lambda value: abs(value - midpoint))]
        selected = [captions[str(key)] for key in candidates[:3]]
        return " ".join(selected).strip()

    def _extract_actions(self, caption: str) -> List[str]:
        action_keywords = [
            "run",
            "running",
            "fall",
            "fight",
            "chase",
            "walk",
            "standing",
            "crowd",
            "hit",
            "grab",
            "carry",
            "enter",
            "leave",
        ]
        lowered = caption.lower()
        found = []
        for keyword in action_keywords:
            if keyword in lowered:
                normalized = keyword.replace("running", "run").replace("standing", "stand")
                if normalized not in found:
                    found.append(normalized)
        return found

    def _extract_entities(self, caption: str) -> List[str]:
        entity_keywords = [
            "person",
            "man",
            "woman",
            "people",
            "car",
            "vehicle",
            "bag",
            "bike",
            "police",
            "store",
            "street",
        ]
        lowered = caption.lower()
        return [keyword for keyword in entity_keywords if keyword in lowered]

    def _scene_context(self, caption: str) -> str:
        if not caption:
            return "unknown scene"
        lowered = caption.lower()
        if "street" in lowered or "road" in lowered:
            return "outdoor street scene"
        if "store" in lowered or "shop" in lowered:
            return "commercial indoor scene"
        if "office" in lowered or "room" in lowered:
            return "indoor room scene"
        return "generic scene"

    def vlm_describe(self, window_input: WindowInput) -> Dict[str, object]:
        caption = ""
        confidence = 0.0
        captions = self._load_caption_map(window_input.video_id)
        if captions:
            caption = self._select_caption(captions, window_input)
            confidence = 0.9 if caption else 0.2
        elif self.caption_backend is not None:
            caption = self.caption_backend(window_input)
            confidence = 0.7 if caption else 0.1
        else:
            caption = "No caption available for this segment."
            confidence = 0.1
        caption = re.sub(r"\s+", " ", caption).strip()
        return {
            "vision_caption": caption,
            "entities": self._extract_entities(caption),
            "actions": self._extract_actions(caption),
            "scene_context": self._scene_context(caption),
            "confidence": confidence,
        }
