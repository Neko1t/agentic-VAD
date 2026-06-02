from __future__ import annotations

from typing import Callable, Dict, List, Optional

from src.core.schemas import WindowInput


class OCRTool:
    def __init__(
        self,
        enabled: bool = False,
        backend_name: Optional[str] = None,
        extract_backend: Optional[Callable[[WindowInput], Dict[str, object]]] = None,
    ):
        self.enabled = enabled
        self.backend_name = backend_name
        self.extract_backend = extract_backend

    def ocr_extract(self, window_input: WindowInput) -> Dict[str, object]:
        if not self.enabled:
            return {"ocr_texts": [], "confidence": 0.0}
        if self.extract_backend is not None:
            result = self.extract_backend(window_input)
            return {
                "ocr_texts": list(result.get("ocr_texts", [])),
                "confidence": float(result.get("confidence", 0.0)),
            }
        if self.backend_name == "easyocr" and window_input.frame_paths:
            try:  # pragma: no cover - optional dependency path
                import easyocr

                reader = easyocr.Reader(["en"], gpu=False)
                texts: List[str] = []
                confidences: List[float] = []
                for frame_path in window_input.frame_paths[:2]:
                    results = reader.readtext(frame_path, detail=1)
                    for _, text, confidence in results:
                        if text.strip():
                            texts.append(text.strip())
                            confidences.append(float(confidence))
                average_conf = sum(confidences) / len(confidences) if confidences else 0.0
                return {"ocr_texts": texts, "confidence": average_conf}
            except Exception:
                return {"ocr_texts": [], "confidence": 0.0}
        return {"ocr_texts": [], "confidence": 0.0}
