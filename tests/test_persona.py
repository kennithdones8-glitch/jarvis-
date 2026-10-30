from jarvis.models.types import Category
from jarvis.persona import CHAT_ONLY_ABILITIES, SYSTEM_PROMPT, priming_messages


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
    assert sum(len(m.content) for m in msgs) < 2500


def test_system_prompt_lists_real_abilities_and_known_gaps():
    text = priming_messages()[0].content
    assert "COMPLETE list" in text
    for ability in CHAT_ONLY_ABILITIES:
        assert ability in text
    for gap in ("email", "volume", "reminders", "files"):
        assert gap in text.split("can NOT")[1]


def test_custom_ability_list_replaces_default():
    text = priming_messages(["search the web via SearXNG"])[0].content
    assert "search the web via SearXNG" in text and CHAT_ONLY_ABILITIES[0] not in text
