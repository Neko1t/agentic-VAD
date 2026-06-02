from src.core.schemas import ModalityConfidence, ObservationCard, TimeSpan


def test_observation_card_defaults():
    card = ObservationCard(
        video_id="video_1",
        window_id="video_1_0001",
        time_span=TimeSpan(start_frame=0, end_frame=15),
    )
    assert card.score_weighted == 0.0
    assert card.modality_confidence == ModalityConfidence()
    assert card.entities == []
