"""PCI leak test 6: no message sent to the LLM contains a PAN-like Luhn-valid sequence."""

import json

from test_5_log_leak_scan import run_dialogue
from va_conftest import make_conversation

from app.processors.scrubber import contains_pan_like


async def test_llm_never_sees_pan():
    conv = make_conversation()
    await run_dialogue(conv)
    assert conv.llm.requests, "the dialogue should have exercised the LLM"
    for messages in conv.llm.requests:
        for m in messages:
            assert not contains_pan_like(m["content"]), m["content"]
    everything = json.dumps(conv.llm.requests)
    assert "capture_url" not in everything and "localhost:8002/capture" not in everything
    assert "tok_" not in everything
