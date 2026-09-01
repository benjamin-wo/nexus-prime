from orchestrator.kernel import is_termination_intent, is_trivial_message


def test_trivial_greetings_reply():
    assert is_trivial_message("hi") != ""
    assert is_trivial_message("Hello!") != ""
    assert is_trivial_message("hey there") != ""
    assert is_trivial_message("good morning") != ""


def test_trivial_thanks_and_bye():
    assert is_trivial_message("thanks") != ""
    assert is_trivial_message("thank you so much") != ""
    assert is_trivial_message("bye") != ""
    assert is_trivial_message("good night") != ""


def test_trivial_ack():
    assert is_trivial_message("ok") != ""
    assert is_trivial_message("got it") != ""
    assert is_trivial_message("sounds good") != ""


def test_trivial_how_are_you():
    assert is_trivial_message("how are you") != ""


def test_request_shaped_messages_are_not_trivial():
    assert is_trivial_message("hi can you log 15 bucks") == ""
    assert is_trivial_message("spent $15 on lunch") == ""
    assert is_trivial_message("check my expenses") == ""
    assert is_trivial_message("what's the weather") == ""
    assert is_trivial_message("delete the coinhako expense") == ""
    assert is_trivial_message("remind me at 6pm") == ""


def test_trivial_rejects_numbers():
    assert is_trivial_message("thanks 5") == ""
    assert is_trivial_message("ok 2") == ""


def test_trivial_rejects_long_text():
    assert is_trivial_message("hi " * 40) == ""


def test_trivial_punctuation_variants():
    assert is_trivial_message("hey!!!") != ""
    assert is_trivial_message("thanks,") != ""


def test_expanded_termination_intents():
    for phrase in ("cancel", "never mind", "that's all for now", "nothing else", "bye", "no thanks"):
        assert is_termination_intent(phrase) is True, phrase
    assert is_termination_intent("cancel my reminder") is False
    assert is_termination_intent("delete the coinhako expense") is False