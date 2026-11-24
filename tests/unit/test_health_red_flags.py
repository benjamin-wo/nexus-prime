"""The red-flag pre-check: what it catches, what it must leave alone, and its fixed texts."""

import pytest

from nexus.domain.health_safety import (
    RedFlagKind,
    Severity,
    has_compensating_language,
    red_flags,
)
from nexus.domain.health_texts import (
    EMERGENCY_NUMBER,
    KKH_PHONE,
    SGH_EDP_EMAIL,
    SOS_PHONE,
    SOS_WHATSAPP,
)

K = RedFlagKind

FLAGGED = [
    # emergencies
    ("I have chest pain when I climb stairs", K.CHEST),
    ("chest tightness during my run", K.CHEST),
    ("there's a pressure in my chest", K.CHEST),
    ("my chest very tight leh", K.CHEST),
    ("My chest feels heavy", K.CHEST),
    ("my chest hurts after the set", K.CHEST),
    ("I think I'm having a heart attack", K.CHEST),
    ("I fainted after my workout", K.FAINTING),
    ("I almost fainted in the MRT", K.FAINTING),
    ("keep feeling faint after breakfast", K.FAINTING),
    ("I blacked out at the gym", K.FAINTING),
    ("I passed out on the bench", K.FAINTING),
    ("I cannot breathe properly", K.BREATHING),
    ("i cant breathe", K.BREATHING),
    ("I can\u2019t catch my breath", K.BREATHING),
    ("having trouble breathing since morning", K.BREATHING),
    ("short of breath while sitting at my desk", K.BREATHING),
    ("shortness of breath at rest", K.BREATHING),
    ("I want to die", K.SUICIDAL),
    ("thinking about suicide", K.SUICIDAL),
    ("I want to kill myself", K.SUICIDAL),
    ("I don't want to live anymore", K.SUICIDAL),
    ("everyone is better off without me", K.SUICIDAL),
    # see a professional
    ("sharp pain in my knee when I squat", K.SHARP_PAIN),
    ("a stabbing pain in my lower back", K.SHARP_PAIN),
    ("my shoulder pain is getting worse each week", K.SHARP_PAIN),
    ("the pain won't go away", K.SHARP_PAIN),
    ("I have numbness in my left hand", K.NUMBNESS),
    ("tingling down my arm", K.NUMBNESS),
    ("my fingers go numb when I deadlift", K.NUMBNESS),
    ("I felt a pop in my knee", K.JOINT_POP),
    ("my shoulder popped during bench", K.JOINT_POP),
    ("something snapped in my ankle", K.JOINT_POP),
    ("my shoulder pops when I press", K.JOINT_POP),
    ("knee clicks and hurts when I squat", K.JOINT_POP),
    ("felt something pop in my back", K.JOINT_POP),
    ("heard a pop in my knee", K.JOINT_POP),
    ("my elbow is popping on every curl", K.JOINT_POP),
    ("wrist clicking and it's painful", K.JOINT_POP),
    ("my hip clicks, sore after squats", K.JOINT_POP),
    ("I'm pregnant, can I still lift?", K.PREGNANCY),
    ("what should I eat during pregnancy", K.PREGNANCY),
    ("I'm 3 months postpartum", K.PREGNANCY),
    ("I'm breastfeeding, how much protein?", K.PREGNANCY),
    ("Can I take creatine with my blood pressure meds?", K.MEDICATION),
    ("is it safe to take fat burners while on antidepressants", K.MEDICATION),
    ("does ibuprofen interact with my supplements", K.MEDICATION),
    ("should I stop taking my metformin if I fast", K.MEDICATION),
    ("I think I have an eating disorder", K.EATING_DISORDER),
    ("I've been purging after dinner", K.EATING_DISORDER),
    ("I make myself throw up after eating", K.EATING_DISORDER),
    ("I use laxatives to lose weight", K.EATING_DISORDER),
    ("I was anorexic as a teenager", K.EATING_DISORDER),
    ("I keep starving myself on weekdays", K.EATING_DISORDER),
    ("I need to burn off what I ate", K.EATING_DISORDER),
]

BENIGN = [
    "chest day today, bench and flys",
    "great chest press session",
    "pain au chocolat for breakfast",
    "no pain no gain",
    "I'm dying to try that place",
    "dying to see the new gym",
    "my legs are dead after leg day",
    "I'm so tired I could sleep for a week",
    "numb from the cold AC in the office",
    "my lips tingle from the mala hotpot",
    "I'm out of breath after the stairs",
    "I'm breathless after my 5k",
    "can't breathe through my nose, blocked",
    "popped into the gym after work",
    "pop music playlist for cardio",
    "pop quiz at work today",
    "k-pop playlist for the gym",
    "popped to the shops after training",
    "pop tarts for breakfast",
    "my knees click on stairs but don't hurt",
    "my knee clicks, painless though",
    "my shoulder clicks sometimes",
    "popped back to the gym",
    "I passed the gym entrance and bought a drink",
    "faint smell of chicken rice",
    "binge-watching shows after my run",
    "I take a multivitamin with breakfast",
    "what vitamins are in kangkong",
    "how much protein is in tempeh",
    "log 82.4 kg this morning",
    "my knee feels a bit stiff today",
    "sharp cheddar on my toast",
    "I'm so hungry",
    "how do I earn my blue badge",
    "purge my closet this weekend",
    "I'm starving, what's near me",
    "",
]


@pytest.mark.parametrize(("text", "kind"), FLAGGED)
def test_flagged(text: str, kind: RedFlagKind) -> None:
    flag = red_flags(text)
    assert flag is not None, text
    assert flag.kind is kind


@pytest.mark.parametrize("text", BENIGN)
def test_benign(text: str) -> None:
    assert red_flags(text) is None, text


def test_there_are_enough_cases() -> None:
    assert len(FLAGGED) + len(BENIGN) >= 30


def test_pregnancy_wording_is_always_flagged() -> None:
    flag = red_flags("pregnancy test aisle was crowded")
    assert flag is not None and flag.kind is K.PREGNANCY


def test_judgement_calls() -> None:
    # Numbness from the cold or a spicy mouth is not a flag; unexplained numbness is.
    assert red_flags("my hands go numb from the cold AC") is None
    assert red_flags("my hands go numb at night") is not None
    # "can't breathe" is flagged unless the nose is the problem.
    assert red_flags("lol i can't breathe") is not None
    # Idioms about dying or killing are not flagged, direct statements are.
    assert red_flags("I could kill myself for eating that") is not None
    assert red_flags("this workout is killing me") is None


def test_emergencies_come_first() -> None:
    both = red_flags("I'm pregnant and I have chest pain")
    assert both is not None and both.kind is K.CHEST
    mixed = red_flags("I'm on medication and I want to die")
    assert mixed is not None and mixed.kind is K.SUICIDAL


def test_case_and_spacing_do_not_matter() -> None:
    flag = red_flags("  CHEST   PAIN  ")
    assert flag is not None and flag.kind is K.CHEST


def test_severities_and_texts() -> None:
    emergency = red_flags("chest pain")
    assert emergency and emergency.severity is Severity.EMERGENCY
    assert EMERGENCY_NUMBER in emergency.text
    suicide = red_flags("I want to die")
    assert suicide and EMERGENCY_NUMBER in suicide.text
    assert SOS_PHONE in suicide.text and SOS_WHATSAPP in suicide.text
    knee = red_flags("sharp pain in my knee")
    assert knee and knee.severity is Severity.SEE_PROFESSIONAL
    ed = red_flags("I think I have an eating disorder")
    assert ed
    for needle in (SGH_EDP_EMAIL, KKH_PHONE, SOS_PHONE):
        assert needle in ed.text
    assert {s.name for s in ed.signposts} >= {"SGH Eating Disorders Programme"}


def test_compensating_language() -> None:
    assert has_compensating_language("I purge after dinner")
    assert has_compensating_language("I take laxatives to lose weight")
    assert not has_compensating_language("I had a big dinner")
    assert not has_compensating_language("my knee popped")
