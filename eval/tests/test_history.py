"""What the driver actually puts on the wire for a follow-up question."""

from __future__ import annotations

import asyncio

import pytest

from eval import run_eval

Observed = run_eval.Observed


def card(narrative: str) -> dict:
    """The minimum an answer needs to count as one."""
    return {"status": "ok", "narrative": narrative}


def case(question: str, history: list[str] | None = None) -> dict:
    spec = {"id": "followup", "question": question,
            "expects": {"status": "ok", "language": "sv"}}
    if history is not None:
        spec["history"] = history
    return spec


@pytest.fixture
def recorder(monkeypatch):
    """Replaces the one function that speaks HTTP, and records what each turn was asked with."""
    sent: list[tuple[str, list[dict[str, str]]]] = []
    answers: dict[str, Observed] = {}

    async def fake_ask(session, question, timeout, history=None):
        # Copied, not aliased: the driver mutates one history list across the conversation,
        # so a shared reference would show every recorded turn as the final state.
        sent.append((question, list(history or [])))
        return answers.get(question, Observed(card=card(f"Svar på {question}")))

    monkeypatch.setattr(run_eval, "ask", fake_ask)
    return sent, answers


def run(spec: dict):
    return asyncio.run(run_eval.run_case(session=None, case=spec, suite="golden",
                                         timeout=1.0, semaphore=asyncio.Semaphore(1)))




def test_a_single_turn_case_still_sends_an_empty_history(recorder):
    sent, _ = recorder
    run(case("Hur mycket sålde vi förra månaden?"))

    assert sent == [("Hur mycket sålde vi förra månaden?", [])]


def test_a_follow_up_is_asked_after_its_set_up_turn(recorder):
    sent, _ = recorder
    run(case("…mätt i antal istället?",
             history=["Vilka produkter säljer bäst i Stockholm?"]))

    assert [question for question, _ in sent] == [
        "Vilka produkter säljer bäst i Stockholm?", "…mätt i antal istället?"]
    assert sent[0][1] == [], "the set-up turn opens the conversation"


def test_the_assistant_turn_is_the_system_s_own_narrative(recorder):
    """Not prose from the YAML."""
    sent, answers = recorder
    answers["Vad sålde vi för i juni 2026?"] = Observed(
        card=card("Ni sålde för 3 374 914,99 kr i juni 2026."))

    run(case("Och förra året då?", history=["Vad sålde vi för i juni 2026?"]))

    assert sent[-1][1] == [
        {"role": "user", "content": "Vad sålde vi för i juni 2026?"},
        {"role": "assistant", "content": "Ni sålde för 3 374 914,99 kr i juni 2026."},
    ]


def test_several_prior_turns_accumulate_in_order(recorder):
    sent, _ = recorder
    run(case("Och bara i Stockholms län?", history=["Fråga ett?", "Fråga två?"]))

    assert [turn["content"] for turn in sent[-1][1]] == [
        "Fråga ett?", "Svar på Fråga ett?", "Fråga två?", "Svar på Fråga två?"]
    assert [turn["role"] for turn in sent[-1][1]] == [
        "user", "assistant", "user", "assistant"]




def test_a_set_up_turn_that_never_answered_fails_the_case_on_the_prelude(recorder):
    """And fails it there rather than asking the follow-up anyway."""
    sent, answers = recorder
    answers["Vilka produkter säljer bäst i Stockholm?"] = Observed(
        error="timed out after 120s waiting for the card")

    result = run(case("…mätt i antal istället?",
                      history=["Vilka produkter säljer bäst i Stockholm?"]))

    assert [question for question, _ in sent] == ["Vilka produkter säljer bäst i Stockholm?"]
    assert not result.passed
    assert [failure.check for failure in result.failures] == ["transport"]
    message = result.failures[0].message
    assert "Vilka produkter säljer bäst i Stockholm?" in message
    assert "timed out" in message


def test_a_set_up_turn_with_a_card_but_no_narrative_is_also_a_broken_prelude(recorder):
    """An empty assistant turn would degrade the case into a single-turn one - passing, and testing
    nothing it claims to test."""
    _, answers = recorder
    answers["Fråga ett?"] = Observed(card=card("   "))

    result = run(case("Och förra året då?", history=["Fråga ett?"]))

    assert not result.passed
    assert "no narrative to carry forward" in result.failures[0].message


def test_a_transport_failure_in_the_prelude_is_not_charged_to_the_model(recorder):
    """It lands in the `transport` family, the column that exists so infrastructure noise does not
    inflate the model's error rate."""
    _, answers = recorder
    answers["Fråga ett?"] = Observed(error="transport error: ConnectError")

    result = run(case("Och förra året då?", history=["Fråga ett?"]))

    assert result.family_tally() == {"transport": (0, 1)}
