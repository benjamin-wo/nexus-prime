"""The voice clips of the evaluation set: each is real Opus-in-Ogg, described by the
manifest, and played by at least one case."""

import asyncio

from nexus.evals import clips
from nexus.evals.cases import CASES


def test_every_clip_is_listed_in_the_manifest_and_the_other_way_round() -> None:
    on_disk = {p.stem for p in clips.CLIPS.glob("*.ogg")}
    assert on_disk == set(clips.manifest())
    assert 10 <= len(on_disk) <= 16
    for entry in clips.manifest().values():
        assert {"expected", "accent", "noise", "seconds"} <= set(entry)
        assert entry["noise"] in {"clean", "noisy"}


def test_clips_are_ogg_and_small() -> None:
    for key in clips.manifest():
        data, mime = asyncio.run(clips.load(key))
        assert data.startswith(b"OggS") and b"OpusHead" in data[:64], key
        assert mime == "audio/ogg"
        assert len(data) < 50_000, key


def test_the_voice_cases_use_clean_and_noisy_clips_and_all_of_them() -> None:
    played = {t.audio for c in CASES for t in c.turns if t.audio}
    assert played == set(clips.manifest())
    noise = {str(clips.manifest()[k]["noise"]) for k in played}
    assert noise == {"clean", "noisy"}
    voice = [c for c in CASES if c.area == "voice"]
    assert len(voice) >= 12
    assert all(c.id.startswith("voice-") for c in voice)
