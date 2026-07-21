"""Regression tests for :func:`parse_model_decision` (#2).

The runtime system prompt teaches the model to emit delegation as
``</response> <brief note> </delegation> <the question>``. Because the
``</response>`` token precedes the delegation tag, a naive earliest-marker
scan misclassifies a real delegation as "response". These tests lock in the
correct (delegation-priority) behavior for the real multi-token format.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from response_format import parse_model_decision


def test_delegation_with_response_prefix_token_not_misclassified():
    """Real-format delegation (</response> note </delegation> Q) -> delegation."""
    raw = "</response> 这个问题我不太确定，转交后台求解器。 </delegation> 查 RTX 5060 Ti 价格"
    decision, clean_text, question = parse_model_decision(raw)
    assert decision == "delegation"
    assert question == "查 RTX 5060 Ti 价格"


def test_delegation_with_open_tag_still_detected():
    raw = "</response> I'll hand this off. <delegation> what is the capital of France?"
    decision, clean_text, question = parse_model_decision(raw)
    assert decision == "delegation"
    assert question == "what is the capital of France?"


def test_bare_delegation_tag():
    decision, _, question = parse_model_decision("</delegation> 查 RTX 5060 Ti 价格")
    assert decision == "delegation"
    assert question == "查 RTX 5060 Ti 价格"


def test_response_token_still_response():
    decision, clean_text, _ = parse_model_decision("</response> hello there")
    assert decision == "response"
    assert clean_text == "hello there"


def test_silence_token_still_silence():
    decision, clean_text, _ = parse_model_decision("</silence>")
    assert decision == "silence"
    assert clean_text == ""


def test_empty_is_silence():
    decision, _, _ = parse_model_decision("")
    assert decision == "silence"


def test_no_token_is_response():
    decision, clean_text, _ = parse_model_decision("just talking to the user")
    assert decision == "response"
    assert clean_text == "just talking to the user"
