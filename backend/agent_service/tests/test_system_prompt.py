import pytest
from app.agent.graph import SYSTEM_PROMPT

def test_system_prompt_contains_missing_data_guard():
    # A substring check on a distinctive phrase is sufficient
    expected_phrase = "If a diagnosis label is missing, empty, or a temporal trend direction is \"indeterminate\""
    assert expected_phrase in SYSTEM_PROMPT, "SYSTEM_PROMPT is missing the guard against missing/indeterminate data"
