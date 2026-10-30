from jarvis.models.types import Category
from jarvis.persona import SYSTEM_PROMPT, priming_messages


def test_persona_denies_fictional_identity_without_priming_it():
    text = SYSTEM_PROMPT.lower()
    assert "not a character from any film" in text
    for word in ("stark", "iron man", "avengers", "marvel"):
        assert word not in text  # naming them primes small models toward the film persona
    assert "never claim" in text and "do not know" in text


def test_priming_messages_are_public_and_short():
    msgs = priming_messages()
    assert [m.role for m in msgs] == ["system", "user", "assistant"]
    assert all(m.category is Category.SYSTEM_PROMPT for m in msgs)
    assert sum(len(m.content) for m in msgs) < 1500
