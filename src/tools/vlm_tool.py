from __future__ import annotations

import atexit
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Sequence

from src.core.schemas import WindowInput


class VLMBackend(Protocol):
    name: str

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        ...


_TEMP_VIDEO_FILES: set[str] = set()


def _cleanup_temp_videos() -> None:
    for path in list(_TEMP_VIDEO_FILES):
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
        _TEMP_VIDEO_FILES.discard(path)


atexit.register(_cleanup_temp_videos)


class PrecomputedCaptionBackend:
    name = "precomputed_caption"

    def __init__(
        self,
        captions_dir: Path,
    ):
        self.captions_dir = captions_dir

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        captions = self._load_caption_map(window_input.video_id)
        if not captions:
            return {
                "vision_caption": "",
                "confidence": 0.0,
                "backend_name": self.name,
                "artifact_refs": [],
            }
        caption = self._select_caption(captions, window_input)
        return {
            "vision_caption": caption,
            "confidence": 0.9 if caption else 0.2,
            "backend_name": self.name,
            "artifact_refs": [str(self.captions_dir / f"{window_input.video_id}.json")],
        }

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


class CallableCaptionBackend:
    name = "callable_caption"

    def __init__(self, caption_backend: Callable[[WindowInput], str]):
        self.caption_backend = caption_backend

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        caption = self.caption_backend(window_input)
        return {
            "vision_caption": caption,
            "confidence": 0.7 if caption else 0.1,
            "backend_name": self.name,
            "artifact_refs": [],
        }


class MockVLMBackend:
    name = "mock_vlm"

    def __init__(self, caption: str = "", captions_by_window: Optional[Dict[str, str]] = None):
        self.caption = caption
        self.captions_by_window = captions_by_window or {}

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        caption = self.captions_by_window.get(window_input.window_id, self.caption)
        return {
            "vision_caption": caption,
            "confidence": 1.0 if caption else 0.0,
            "backend_name": self.name,
            "artifact_refs": [],
        }


class NullVLMBackend:
    name = "null_vlm"

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        return {
            "vision_caption": "No caption available for this segment.",
            "confidence": 0.1,
            "backend_name": self.name,
            "artifact_refs": [],
        }


class VideoLLaMABackend:
    name = "videollama3"

    def __init__(
        self,
        video_root: Path,
        model_path: Path | None = None,
        runtime_device: str = "cuda:0",
        max_frames: int = 10,
        fps: int = 2,
        max_new_tokens: int = 256,
        temperature: float = 0.1,
    ):
        self.video_root = video_root
        self.model_path = str(model_path) if model_path else "DAMO-NLP-SG/VideoLLaMA3-7B"
        self.runtime_device = runtime_device
        self.max_frames = max_frames
        self.fps = fps
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self._model = None
        self._processor = None
        self._torch = None
        self._cv2 = None
        self._video_cache: dict[str, tuple[float, float]] = {}

    def describe(self, window_input: WindowInput) -> Dict[str, object]:
        video_path = self._resolve_video_path(window_input)
        if video_path is None:
            return {
                "vision_caption": "",
                "confidence": 0.0,
                "backend_name": self.name,
                "artifact_refs": [],
            }
        model, processor = self._load_model()
        torch = self._load_torch()
        start_time, end_time = self._resolve_time_span(video_path, window_input)
        conversation = [
            {
                "role": "system",
                "content": (
                    "You are an AI assistant analyzing this video segment. "
                    "Summarize the main events or actions in a concise way."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "video",
                        "video": {
                            "video_path": str(video_path),
                            "fps": self.fps,
                            "start_time": start_time,
                            "end_time": end_time,
                            "max_frames": self.max_frames,
                        },
                    }
                ],
            },
        ]
        with torch.inference_mode():
            inputs = processor(
                conversation=conversation,
                add_system_prompt=True,
                add_generation_prompt=True,
                return_tensors="pt",
            )
            device = next(model.parameters()).device
            float_dtype = next(model.parameters()).dtype
            for key, value in inputs.items():
                if hasattr(value, "to"):
                    if key == "pixel_values":
                        inputs[key] = value.to(device, dtype=float_dtype)
                    else:
                        inputs[key] = value.to(device)
            output_ids = model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
            )
            caption = processor.batch_decode(output_ids, skip_special_tokens=True)[0].strip()
        return {
            "vision_caption": caption,
            "confidence": 0.95 if caption else 0.0,
            "backend_name": self.name,
            "artifact_refs": [str(video_path)],
        }

    def close(self) -> None:
        torch = self._torch
        self._model = None
        self._processor = None
        if torch is not None and hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    def _load_model(self):
        if self._model is not None and self._processor is not None:
            return self._model, self._processor
        torch = self._load_torch()
        from transformers import AutoModelForCausalLM, AutoProcessor

        device_map = self.runtime_device if torch.cuda.is_available() else "cpu"
        float_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            trust_remote_code=True,
            device_map=device_map,
            torch_dtype=float_dtype,
            attn_implementation="flash_attention_2" if torch.cuda.is_available() else "eager",
        )
        self._processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
        return self._model, self._processor

    def _load_torch(self):
        if self._torch is None:
            import torch

            self._torch = torch
        return self._torch

    def _load_cv2(self):
        if self._cv2 is None:
            import cv2

            self._cv2 = cv2
        return self._cv2

    def _resolve_video_path(self, window_input: WindowInput) -> Path | None:
        direct = Path(window_input.video_path)
        if direct.exists() and direct.is_file():
            return direct
        stem = Path(window_input.video_path).stem or window_input.video_id
        for extension in (".mp4", ".avi", ".mov", ".mkv"):
            candidate = self.video_root / f"{stem}{extension}"
            if candidate.exists():
                return candidate
        if window_input.frame_paths:
            return self._build_temp_video_from_frames(window_input)
        return None

    def _build_temp_video_from_frames(self, window_input: WindowInput) -> Path | None:
        frame_paths = [Path(frame_path) for frame_path in window_input.frame_paths if Path(frame_path).exists()]
        if not frame_paths:
            return None
        cv2 = self._load_cv2()
        first_frame = cv2.imread(str(frame_paths[0]))
        if first_frame is None:
            return None
        height, width = first_frame.shape[:2]
        temp_file = tempfile.NamedTemporaryFile(prefix=f"{window_input.video_id}_", suffix=".mp4", delete=False)
        temp_file.close()
        writer = cv2.VideoWriter(
            temp_file.name,
            cv2.VideoWriter_fourcc(*"mp4v"),
            max(1, self.fps),
            (width, height),
        )
        for frame_path in frame_paths:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                continue
            writer.write(frame)
        writer.release()
        _TEMP_VIDEO_FILES.add(temp_file.name)
        return Path(temp_file.name)

    def _resolve_time_span(self, video_path: Path, window_input: WindowInput) -> tuple[float, float]:
        if video_path.as_posix() not in self._video_cache:
            cv2 = self._load_cv2()
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                self._video_cache[video_path.as_posix()] = (0.0, 0.0)
            else:
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
                duration = frame_count / fps if fps > 0 else 0.0
                capture.release()
                self._video_cache[video_path.as_posix()] = (fps, duration)
        fps, duration = self._video_cache[video_path.as_posix()]
        if video_path.as_posix() in _TEMP_VIDEO_FILES:
            return 0.0, duration
        if window_input.time_span.start_time is not None and window_input.time_span.end_time is not None:
            start_time = float(window_input.time_span.start_time)
            end_time = float(window_input.time_span.end_time)
        elif fps > 0:
            start_time = float(window_input.time_span.start_frame) / fps
            end_time = float(window_input.time_span.end_frame) / fps
        else:
            start_time = 0.0
            end_time = 0.0
        if duration > 0:
            start_time = max(0.0, min(start_time, duration))
            end_time = max(start_time, min(end_time, duration))
        return start_time, end_time


class VLMTool:
    def __init__(
        self,
        captions_dir: Optional[Path] = None,
        caption_backend: Optional[Callable[[WindowInput], str]] = None,
        backend: Optional[VLMBackend] = None,
        backends: Optional[Sequence[VLMBackend]] = None,
    ):
        self.backends: List[VLMBackend] = []
        if backends is not None:
            self.backends.extend(backends)
        if backend is not None:
            self.backends.append(backend)
        if captions_dir is not None:
            self.backends.append(PrecomputedCaptionBackend(captions_dir))
        if caption_backend is not None:
            self.backends.append(CallableCaptionBackend(caption_backend))
        if not self.backends:
            self.backends.append(NullVLMBackend())

    def close(self) -> None:
        for backend in self.backends:
            close = getattr(backend, "close", None)
            if callable(close):
                close()

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
        result = self._describe_with_first_available_backend(window_input)
        caption = str(result.get("vision_caption", result.get("caption", "")))
        confidence = float(result.get("confidence", 0.0))
        caption = re.sub(r"\s+", " ", caption).strip()
        return {
            "vision_caption": caption,
            "entities": self._extract_entities(caption),
            "actions": self._extract_actions(caption),
            "scene_context": self._scene_context(caption),
            "confidence": confidence,
            "backend_name": str(result.get("backend_name", "unknown_vlm")),
            "artifact_refs": list(result.get("artifact_refs", [])),
        }

    def _describe_with_first_available_backend(self, window_input: WindowInput) -> Dict[str, object]:
        fallback: Dict[str, object] = {}
        for backend in self.backends:
            result = backend.describe(window_input)
            caption = str(result.get("vision_caption", result.get("caption", ""))).strip()
            fallback = result
            if caption:
                return result
        return fallback
