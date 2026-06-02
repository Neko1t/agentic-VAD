from src.core.config import ScoringConfig
from src.core.schemas import ModalityConfidence, ObservationCard, TimeSpan
from src.tools.score_tool import ScoreTool


def test_score_tool_downweights_low_confidence_ocr():
    tool = ScoreTool(ScoringConfig())
    card = ObservationCard(
        video_id="v1",
        window_id="w1",
        time_span=TimeSpan(start_frame=0, end_frame=15),
        vision_caption="A person is walking on the street.",
        actions=["walk"],
        ocr_texts=["EMERGENCY WEAPON ALERT"],
        modality_confidence=ModalityConfidence(vision_conf=0.9, audio_conf=0.0, ocr_conf=0.1),
    )
    scored = tool.score_observation(card)
    assert scored["score_raw"] >= 9.0
    assert scored["score_weighted"] < scored["score_raw"]
    assert any("OCR" in reason for reason in scored["reason_trace"])
