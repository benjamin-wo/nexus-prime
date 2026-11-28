"""Fixed referral texts for Health's safety layer.

These are never written by the model: a red flag or a safety signal returns one of them as it
is. Wording is plain and kind, with no lecture and no judgement about food or bodies.

Phone numbers and addresses below came from the research report (24 Nov 2026) and must be
re-verified on the official sites before release (SGH, KKH via HealthHub, Samaritans of
Singapore). Singapore has no dedicated national eating-disorder helpline.
"""

from dataclasses import dataclass

# RE-VERIFY BEFORE RELEASE: every number and address in this module.
EMERGENCY_NUMBER = "995"  # Singapore ambulance and emergencies
SOS_PHONE = "1767"  # Samaritans of Singapore, 24 hours
SOS_WHATSAPP = "9151 1767"
SGH_EDP_EMAIL = "eatingdisorders@sgh.com.sg"  # SGH Eating Disorders Programme, ages 13+
KKH_PHONE = "6294 4050"  # KKH, for under-18s (appointments)


@dataclass(frozen=True, slots=True)
class Signpost:
    """One place to get help."""

    name: str
    contact: str
    note: str


SIGNPOST_SOS = Signpost(
    "Samaritans of Singapore",
    f"{SOS_PHONE}, or WhatsApp {SOS_WHATSAPP}",
    "Someone to talk to, any time.",
)
SIGNPOST_SGH = Signpost(
    "SGH Eating Disorders Programme",
    SGH_EDP_EMAIL,
    "Specialist support for ages 13 and up.",
)
SIGNPOST_KKH = Signpost(
    "KK Women's and Children's Hospital (KKH)",
    KKH_PHONE,
    "Appointments for under-18s.",
)
SIGNPOST_EMERGENCY = Signpost("Emergency", EMERGENCY_NUMBER, "For anything urgent.")

# Shown with a soft check-in or an eating-disorder disclosure. KKH is added for under-18s.
ED_SIGNPOSTS = (SIGNPOST_SGH, SIGNPOST_SOS)
ED_SIGNPOSTS_UNDER_18 = (SIGNPOST_KKH, SIGNPOST_SGH, SIGNPOST_SOS)

TEXT_EMERGENCY = (
    "What you describe could be serious, and I can't assess it from here. Please call "
    f"{EMERGENCY_NUMBER} now, or ask someone near you to. If you can, stay with someone until "
    "help arrives."
)
TEXT_SUICIDE = (
    "I'm really sorry it's this heavy right now, and I'm glad you said it. If you might act on "
    f"these thoughts or you're in danger, please call {EMERGENCY_NUMBER} now. You can also talk "
    f"to Samaritans of Singapore at any hour: call {SOS_PHONE}, or WhatsApp {SOS_WHATSAPP}. "
    "You don't have to handle this alone."
)
TEXT_PAIN = (
    "That is worth having a doctor or physiotherapist look at before you train on it. I can't "
    "tell what is going on from here, so I'll leave training suggestions out for now. If it "
    f"gets worse quickly or you feel unwell, call {EMERGENCY_NUMBER} or go to an A&E."
)
TEXT_NUMBNESS = (
    "Numbness or tingling is worth checking with a doctor, especially if it keeps coming back "
    "or came on suddenly. I can't tell the cause from here, so I'll pause training suggestions "
    f"for now. If it comes with weakness, trouble speaking or a drooping face, call "
    f"{EMERGENCY_NUMBER}."
)
TEXT_JOINT = (
    "A joint that popped, especially with pain, swelling or giving way, should be seen by a "
    "doctor or physiotherapist before you load it again. I'll leave training suggestions for "
    "that area out until then."
)
TEXT_PREGNANCY = (
    "Pregnancy and the months after birth change what is right for your body, so training and "
    "eating plans are best made with your doctor or midwife. I won't set targets or plans for "
    "this stage, but I'm happy to help log things you want to keep track of."
)
TEXT_MEDICATION = (
    "Whether something is fine alongside your medication or supplements is a question for your "
    "doctor or pharmacist, who know what you take. I can't judge it, so I won't guess."
)
TEXT_EATING_DISORDER = (
    "Thank you for telling me. You deserve support from people who specialise in this. The SGH "
    f"Eating Disorders Programme takes people from 13 up: {SGH_EDP_EMAIL}. If you are under 18, "
    f"KKH can help: {KKH_PHONE}. Samaritans of Singapore are there any time: {SOS_PHONE}, or "
    f"WhatsApp {SOS_WHATSAPP}. I'll keep calorie targets and numbers out of our chats."
)
TEXT_CHECK_IN = (
    "I've noticed some patterns in your logs lately that can mean things are hard. No judgement "
    "at all. If you'd like to talk to someone, the contacts below are there for you, and I'll "
    "keep calorie targets switched off for now."
)


# Why a weight-loss goal wasn't set, by the gate's reason code, in plain words. The same
# sentences as ``web/src/health/safety.ts``: keep the two in step.
GATE_TEXT: dict[str, str] = {
    "under_18": "Weight-loss goals aren't available under 18.",
    "low_bmi": "Weight-loss goals aren't available when BMI is below 18.5.",
    "ed_history": "A weight-loss goal is off because you told me about an eating-disorder history.",
    "age_unknown": "Add your birth year to set a weight-loss goal.",
    "bmi_unknown": "Add your height and a weigh-in to set a weight-loss goal.",
}
