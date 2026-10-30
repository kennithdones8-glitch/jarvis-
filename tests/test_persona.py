from jarvis.models.types import Category
from jarvis.persona import SYSTEM_PROMPT, system_message


def test_persona_states_it_is_not_the_fictional_character():
    text = SYSTEM_PROMPT.lower()
    assert "not the fictional" in text and "tony stark" in text
    assert "never claim" in text and "do not know" in text


def test_persona_is_public_system_prompt_and_short():
    m = system_message()
    assert m.role == "system" and m.category is Category.SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT) < 1500  # small local models follow short prompts better
