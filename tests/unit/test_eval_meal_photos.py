"""The meal photo scorer: MAPE and coverage from made-up numbers, and zero photos."""

import asyncio
from datetime import date
from pathlib import Path

import pytest

from nexus.agent.meal_reader import MealDraft
from nexus.evals import meal_photos as scorer
from nexus.evals.meal_photos import Prediction, Reference

REF = Reference("a.jpg", ("rice",), (100.0,), 400.0, "weighed")


def test_mape_and_coverage() -> None:
    report = scorer.score(
        [
            (REF, Prediction(300.0, 250.0, 450.0)),  # 25% off, inside
            (REF, Prediction(500.0, 450.0, 550.0)),  # 25% off, outside
            (REF, Prediction(400.0, 0.0, 0.0, ("kangkong",))),  # skipped
        ]
    )
    assert report.scored == 2 and report.skipped == 1
    assert report.mape == pytest.approx(0.25) and report.coverage == pytest.approx(0.5)
    assert "MAPE 25.0%" in report.text() and "coverage 50.0%" in report.text()


def test_the_committed_manifest_is_empty_and_scores_as_no_photos_yet() -> None:
    assert scorer.load_manifest() == []
    assert scorer.score([]).text() == "no photos yet"
    assert scorer.main(["--check"]) == 0


def test_running_with_no_photos_never_calls_the_reader() -> None:
    class Never:
        async def read(
            self, image: bytes, mime_type: str, caption: str | None, *, today: date | None = None
        ) -> MealDraft:
            raise AssertionError("no photo, no read")

    assert asyncio.run(scorer.run(Never())).text() == "no photos yet"


def test_a_bad_manifest_names_its_entry(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text('[{"file": "x.jpg", "items": ["a"], "grams": []}]')
    with pytest.raises(ValueError, match="entry 0"):
        scorer.load_manifest(tmp_path)


def test_predict_uses_the_database_and_the_photo_range() -> None:
    from nexus.infra.foods import load_foods

    draft = MealDraft.model_validate(
        {
            "items": [
                {"name": "white rice", "grams_estimate": 200},
                {"name": "zzzz", "grams_estimate": 5},
            ]
        }
    )
    got = scorer.predict(draft, load_foods())
    assert got.unresolved == ("zzzz",) and got.point == pytest.approx(260.0, rel=0.01)
    assert got.low < got.point < got.high
