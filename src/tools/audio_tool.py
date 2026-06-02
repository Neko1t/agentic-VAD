from __future__ import annotations

from typing import Callable, Dict, Optional

from src.core.schemas import WindowInput


class AudioTool:
    def __init__(
        self,
        enabled: bool = False,
        backend_name: Optional[str] = None,
        transcribe_backend: Optional[Callable[[WindowInput], Dict[str, object]]] = None,
    ):
        self.enabled = enabled
        self.backend_name = backend_name
        self.transcribe_backend = transcribe_backend

    def audio_describe(self, window_input: WindowInput) -> Dict[str, object]:
        if not self.enabled:
            return {"audio_events": [], "transcript": "", "confidence": 0.0}
        if self.transcribe_backend is not None:
            result = self.transcribe_backend(window_input)
            return {
                "audio_events": list(result.get("audio_events", [])),
                "transcript": str(result.get("transcript", "")),
                "confidence": float(result.get("confidence", 0.0)),
            }
        if self.backend_name == "faster-whisper" and window_input.audio_path:
            try:  # pragma: no cover - optional dependency path
                from faster_whisper import WhisperModel

                model = WhisperModel("small", device="cpu", compute_type="int8")
                segments, _ = model.transcribe(window_input.audio_path)
                transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
                events = []
                lowered = transcript.lower()
                if "help" in lowered or "scream" in lowered:
                    events.append("distress_audio")
                return {"audio_events": events, "transcript": transcript, "confidence": 0.6 if transcript else 0.0}
            except Exception:
                return {"audio_events": [], "transcript": "", "confidence": 0.0}
        return {"audio_events": [], "transcript": "", "confidence": 0.0}
