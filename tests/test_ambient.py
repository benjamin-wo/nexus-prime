from datetime import datetime, timezone

from core.ambient import should_deliver


def _now_sgt(hour: int, minute: int = 0) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime(2026, 8, 8, hour, minute, tzinfo=ZoneInfo("Asia/Singapore"))


def test_c8_probe1_small_mismatch_suppressed_in_quiet_hours():
    trigger = {"kind": "expense_mismatch", "trigger_id": "t-1", "amount_diff": 4.0}
    deliver, reason = should_deliver(trigger, _now_sgt(2, 40), "Asia/Singapore")
    assert deliver is False
    assert "quiet hours" in reason


def test_c8_probe2_urgent_trigger_lands_in_quiet_hours():
    big_mismatch = {"kind": "expense_mismatch", "trigger_id": "t-2", "amount_diff": 500.0}
    deliver, reason = should_deliver(big_mismatch, _now_sgt(2, 40), "Asia/Singapore")
    assert deliver is True
    assert reason == "deliverable (urgency=urgent)"

    urgent_keyword = {
        "kind": "scheduled_job",
        "trigger_id": "t-3",
        "message": "URGENT security alert from your bank",
    }
    deliver, reason = should_deliver(urgent_keyword, _now_sgt(2, 40), "Asia/Singapore")
    assert deliver is True


def test_c8_probe3_no_trigger_record_never_guesses():
    deliver, reason = should_deliver(None, _now_sgt(14, 0), "Asia/Singapore")
    assert deliver is False
    assert "never guesses" in reason
    deliver2, _ = should_deliver({"kind": "scheduled_job"}, _now_sgt(14, 0), "Asia/Singapore")
    assert deliver2 is False


def test_c8_probe4_routine_trigger_lands_after_quiet_hours():
    trigger = {"kind": "expense_mismatch", "trigger_id": "t-4", "amount_diff": 4.0}
    deliver, reason = should_deliver(trigger, _now_sgt(10, 0), "Asia/Singapore")
    assert deliver is True
