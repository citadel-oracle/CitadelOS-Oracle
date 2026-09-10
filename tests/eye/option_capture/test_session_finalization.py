"""E4A-E Test for Session Finalization & State Transitions."""

import pytest
from src.eye.option_capture.session import OptionCaptureSession
from src.eye.option_capture.config import CaptureConfig
from src.eye.option_capture.contracts import CaptureSessionState


def test_session_state_transitions():
    cfg = CaptureConfig()
    sess = OptionCaptureSession.create("SESS:TEST:1", "2026-08-07", cfg)
    assert sess.state == CaptureSessionState.PLANNED

    sess.transition_to(CaptureSessionState.CAPTURING)
    assert sess.state == CaptureSessionState.CAPTURING
    assert sess.finalized_at_utc is None

    sess.transition_to(CaptureSessionState.COMPLETE)
    assert sess.state == CaptureSessionState.COMPLETE
    assert sess.finalized_at_utc is not None
