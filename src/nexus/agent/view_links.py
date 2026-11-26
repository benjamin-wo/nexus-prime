"""The screens Prime can bring up, by name: the one place that says which view is which page.

``show`` (and the "Open ..." buttons on replies) look a view up here. The names are the start
of a shared catalogue of views; a page moves only by changing its path here.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class View:
    path: str  # a route of the web app
    line: str  # the one line Prime says when it brings the view up
    button: str  # the label of the button that opens it
    where: str  # where it is in the app, for a reply with no link to give


VIEWS: dict[str, View] = {
    "health.today": View("/health", "Here's your day.", "Open Today", "Health, under Today"),
    "health.weight_trend": View(
        "/health", "Here's your weight trend.", "Open weight trend", "Health, under Today"
    ),
    "health.workout": View(
        "/health/gym", "Here's your workout.", "Open workout", "Health, under Gym"
    ),
    "health.records": View(
        "/health/gym/history", "Here are your records.", "Open records", "Health, under Gym"
    ),
    "finance.month_outlook": View(
        "/accounting", "Here's your month.", "Open month outlook", "Finance, under Overview"
    ),
    "finance.budgets": View(
        "/accounting/budgets", "Here are your budgets.", "Open budgets", "Finance, under Budgets"
    ),
    "travel.trips": View("/travel", "Here are your trips.", "Open trips", "Travel"),
    "invest.portfolio": View(
        "/investment", "Here's your portfolio.", "Open portfolio", "Investments"
    ),
}
