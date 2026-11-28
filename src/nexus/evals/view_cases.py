"""Eval cases for views (ADR 0005): which hand-built views a turn should bring into the chat.

Each case is an ordinary ``Case`` (area ``views``) plus a label: the views each turn should
open. Left out, the label of the last turn comes from the case's expected tools through the
catalog (``views.SURFACING``), so a case that expects ``month_outlook`` expects the month
outlook; a case that expects only tools that open nothing expects silence. A wrong set never
fails the case: it is scored on its own (``view_metrics``), beside the pass rate.

Figures are the seed's (28 September 2026). Ledger questions ("what did I spend at
Kopitiam") have no view yet (``finance.transactions`` is planned), so they are not here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from nexus.agent.views import SURFACING, ViewKind, live, surfaced
from nexus.evals.cases import Call, Case, Turn
from nexus.evals.checks import BudgetIs, Logged
from nexus.evals.view_metrics import TurnViews
from nexus.infra.llm.factory import text_of

Views = tuple[ViewKind, ...]

_OUTLOOK: Views = (ViewKind.MONTH_OUTLOOK,)
_BUDGETS: Views = (ViewKind.BUDGETS,)
_SPENDING: Views = (ViewKind.SPENDING,)
_TRIP: Views = (ViewKind.TRIP_BUDGET,)
_PORTFOLIO: Views = (ViewKind.PORTFOLIO,)
_TODAY: Views = (ViewKind.TODAY,)
_WEIGHT: Views = (ViewKind.WEIGHT_TREND,)
_WORKOUT: Views = (ViewKind.WORKOUT,)
_RECORDS: Views = (ViewKind.RECORDS,)
_NONE: Views = ()


@dataclass(frozen=True, slots=True)
class ViewCase:
    case: Case
    turns: tuple[Views | None, ...]  # per turn; None: from the expected tools (last turn only)
    distractor: bool = False


def derived_views(tools: list[str]) -> frozenset[str]:
    """The live views these tools open, through the catalog's mapping."""
    return frozenset(SURFACING[t].value for t in tools if t in SURFACING and live(SURFACING[t]))


def expected_views(vc: ViewCase) -> list[frozenset[str] | None]:
    """The views each turn should open, as ``ViewKind`` values; None leaves a turn unscored."""
    case = vc.case
    out: list[frozenset[str] | None] = []
    last = len(case.turns) - 1
    for n, stated in enumerate(vc.turns):
        if stated is not None:
            out.append(frozenset(v.value for v in stated))
            continue
        tools = [c.tool for c in case.calls] + (list(case.used) if last == 0 else [])
        out.append(derived_views(tools) if n == last and tools else None)
    return out


def _v(
    case_id: str,
    *turns: str | tuple[str, Views],
    views: Views | None = None,
    distractor: bool = False,
    **kw: object,
) -> ViewCase:
    """A views case. A turn is its text, or (text, views). ``views`` labels the last turn
    when it has none of its own; with neither, the expected tools label it. Every case is a
    question unless it says ``unchanged=False``."""
    kw.setdefault("unchanged", True)
    texts = [t if isinstance(t, str) else t[0] for t in turns]
    labels: list[Views | None] = [None if isinstance(t, str) else t[1] for t in turns]
    if views is not None and labels[-1] is None:
        labels[-1] = views
    case = Case(f"views-{case_id}", "views", tuple(Turn(t) for t in texts), **kw)  # type: ignore[arg-type]
    return ViewCase(case, tuple(labels), distractor)


VIEW_SETS: tuple[ViewCase, ...] = (
    # --- Finance: one view, from the tool that answers ------------------------------------
    _v("outlook-month", "how's my month looking?", calls=(Call("month_outlook"),)),
    _v("outlook-month-end", "where will i end up at the end of the month?",
       calls=(Call("month_outlook"),)),
    _v("outlook-august", "how did august go overall?",
       calls=(Call("month_outlook", {"month": "2026-08"}),)),
    _v("outlook-on-track", "am i on track this month?", views=_OUTLOOK),
    _v("budgets-how", "how are my budgets doing?", calls=(Call("list_budgets"),)),
    _v("budgets-dining-left", "how much of my dining budget is left?",
       calls=(Call("list_budgets"),)),
    _v("budgets-over", "am i over on any budget?", calls=(Call("list_budgets"),)),
    _v("spending-where", "where did my money go this month?", views=_SPENDING),
    _v("spending-by-category", "break down my spending by category for september",
       views=_SPENDING),
    _v("trip-how", "how's the japan trip budget looking?", calls=(Call("trip_status"),)),
    _v("trip-left", "how much do i have left to spend in japan?", calls=(Call("trip_status"),)),
    _v("trip-spent", "what have i spent on the tokyo trip so far?", views=_TRIP),
    _v("portfolio-how", "how's my portfolio doing?", calls=(Call("show_portfolio"),)),
    _v("portfolio-holdings", "what stocks do I hold?", calls=(Call("show_portfolio"),)),
    # --- "Show me": the user asks for the screen itself -----------------------------------
    _v("show-month", "show me my month", views=_OUTLOOK),
    _v("show-budgets", "pull up my budgets", views=_BUDGETS),
    _v("show-trip", "open the japan trip's money", views=_TRIP),
    _v("show-august", "put august's outlook up", views=_OUTLOOK),
    _v("show-portfolio", "show me my portfolio", views=_PORTFOLIO),
    # --- Composite: a question about two things opens both --------------------------------
    # Affordability is planned, so "can I afford" is answered by the month outlook for now.
    _v("afford-trip-march", "can i afford a 2,000 trip in march?", views=_OUTLOOK),
    _v("afford-dinner", "can i afford a 500 dinner this month?", views=_OUTLOOK),
    _v("afford-phone", "should i buy a 1,500 phone this month or wait?", views=_OUTLOOK),
    _v("trip-and-month", "how's the japan budget, and how's my month looking overall?",
       views=(ViewKind.TRIP_BUDGET, ViewKind.MONTH_OUTLOOK)),
    _v("budgets-and-month", "how are my budgets, and where does the month end up?",
       views=(ViewKind.BUDGETS, ViewKind.MONTH_OUTLOOK)),
    # --- Health (wellness only) -----------------------------------------------------------
    _v("health-food-log", "had chicken rice for lunch", food=True, unchanged=False,
       calls=(Call("log_food"),)),
    _v("health-food-log-two", "2 eggs and a slice of toast for breakfast", food=True,
       unchanged=False, calls=(Call("log_food"),)),
    _v("health-food-today", "what have i eaten today?", food=True, calls=(Call("food_today"),)),
    _v("health-show-day", "show me my day", gym=True, views=_TODAY),
    _v("health-weight-trend", "show my weight trend", gym=True, views=_WEIGHT),
    _v("health-weight-log", "i weigh 82 kg this morning", gym=True, unchanged=False,
       calls=(Call("log_weight"),)),
    _v("health-workout-today", "what's my workout today?", gym=True,
       calls=(Call("todays_workout"),)),
    _v("health-workout-suggest", "back workout today, 45 min gym", gym=True, unchanged=False,
       calls=(Call("suggest_workout", {}),)),
    _v("health-bench-pr", "what's my bench PR?", gym=True, calls=(Call("personal_records"),)),
    _v("health-records", "show me my records", gym=True, views=_RECORDS),
    # --- Cross-domain: two domains in one turn --------------------------------------------
    _v("cross-eat-and-month", "what have i eaten today, and how's my month looking?",
       food=True, views=(ViewKind.TODAY, ViewKind.MONTH_OUTLOOK)),
    _v("cross-bench-and-budgets", "what's my bench PR, and how are my budgets?", gym=True,
       views=(ViewKind.RECORDS, ViewKind.BUDGETS)),
    # --- Distractors: Health is on, but the question is about money (and the other way) ---
    _v("distract-gym-budget", "how's my dining out budget?", gym=True, distractor=True,
       calls=(Call("list_budgets"),)),
    _v("distract-weight-money", "i'm trying to lose weight, how's my month looking?", gym=True,
       distractor=True, views=_OUTLOOK),
    _v("distract-lunch-expense", "log lunch 8.50 at kopitiam", food=True, distractor=True,
       views=_NONE, unchanged=False, checks=(Logged("8.50"),)),
    _v("distract-gym-fee", "log gym membership 59", gym=True, distractor=True, views=_NONE,
       unchanged=False, checks=(Logged("59"),)),
    # --- Correct silence: small talk, sums, and writes ------------------------------------
    _v("silence-thanks", "thanks!", views=_NONE),
    _v("silence-hello", "hey", views=_NONE),
    _v("silence-ok", "ok got it", views=_NONE),
    _v("silence-joke", "tell me a joke", views=_NONE),
    _v("silence-what-can-you-do", "what can you do?", views=_NONE),
    _v("silence-capital", "what's the capital of japan?", views=_NONE),
    _v("silence-percent", "what's 18% of 2350", views=_NONE, reply=("423",)),
    _v("silence-payday", "when's payday?", views=_NONE),
    _v("silence-log-coffee", "log coffee 5.50", views=_NONE, unchanged=False,
       checks=(Logged("5.50"),)),
    _v("silence-log-grab", "grab 12.40", views=_NONE, unchanged=False,
       checks=(Logged("12.40", "grab"),)),
    _v("silence-income", "got paid 250 for a freelance job today", views=_NONE,
       unchanged=False, checks=(Logged("250", direction="in"),)),
    _v("silence-set-budget", "set a groceries budget of 400 a month", views=_NONE,
       unchanged=False, checks=(BudgetIs("Groceries", "400"),)),
    _v("silence-health-thanks", "thanks, that's great", gym=True, views=_NONE),
    # --- Follow-ups: the next turn updates the same kind of view, moves to another, or none
    _v("followup-last-month", ("how's my month looking?", _OUTLOOK), "and last month?",
       views=_OUTLOOK),
    _v("followup-july", ("how did august go?", _OUTLOOK), "and july?", views=_OUTLOOK),
    _v("followup-budgets-august", ("how are my budgets?", _BUDGETS), "and in august?",
       views=_BUDGETS),
    _v("followup-switch", ("how are my budgets?", _BUDGETS),
       "and where does the month end up?", views=_OUTLOOK),
    _v("followup-thanks", ("how's the japan trip budget?", _TRIP), "great, thanks",
       views=_NONE),
    _v("followup-health-switch", ("what's my bench PR?", _RECORDS),
       "and how are my budgets?", gym=True, views=_BUDGETS),
    _v("followup-health-weight", ("show my weight trend", _WEIGHT), "ok thanks",
       gym=True, views=_NONE),
)  # fmt: skip

VIEW_CASES: tuple[Case, ...] = tuple(vc.case for vc in VIEW_SETS)
LABELS: dict[str, ViewCase] = {vc.case.id: vc for vc in VIEW_SETS}


def opened_in(messages: Sequence[BaseMessage], *, skip: str) -> list[dict[str, Any]]:
    """The live views a turn's tool calls opened, as ``{"view": kind}``, in order, once each.
    A call that came back as an error opens nothing. The model's calls are in its messages
    (``skip`` names the flag of the code's own, which are not its calls) and the answers in
    the tool messages that follow."""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for message in messages:
        if isinstance(message, AIMessage) and not message.additional_kwargs.get(skip):
            calls.update({str(c["id"]): (c["name"], dict(c["args"])) for c in message.tool_calls})
    for message in messages:
        if isinstance(message, ToolMessage) and text_of(message.content).startswith("Error:"):
            calls.pop(message.tool_call_id, None)
    opened: list[str] = []
    for tool, args in calls.values():
        view = surfaced(tool, args)
        if view is not None and live(view) and view.value not in opened:
            opened.append(view.value)
    return [{"view": v} for v in opened]


def turn_views(case_id: str, opened: Sequence[frozenset[str]], round_no: int) -> list[TurnViews]:
    """A case's turns as the view figures see them: what each opened against what it should
    have. Empty for a case with no view label; a case that crashed part way is scored on the
    turns it finished."""
    labelled = LABELS.get(case_id)
    if labelled is None:
        return []
    wanted = expected_views(labelled)
    return [
        TurnViews(
            wanted[n], actual, follow_up=n > 0, distractor=labelled.distractor, round_no=round_no
        )
        for n, actual in enumerate(opened)
    ]
