"""The screens Prime can bring up by name, read from the view catalog (``views.CATALOG``).

``show`` (and the "Open ..." buttons on replies) look a view up here. A page moves only by
changing its path in the catalog.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from nexus.agent.links import app_link
from nexus.agent.views import CATALOG, ViewRef


@dataclass(frozen=True, slots=True)
class View:
    path: str  # a route of the web app
    line: str  # the one line Prime says when it brings the view up
    button: str  # the label of the button that opens it
    where: str  # where it is in the app, for a reply with no link to give


VIEWS: dict[str, View] = {
    spec.name.value: View(spec.path, spec.show.line, spec.show.button, spec.show.where)
    for spec in CATALOG.values()
    if spec.show is not None
}


OPEN_IN_NEXUS = "Open in Nexus"


def open_in_nexus(views: Sequence[ViewRef], origin: str | None) -> tuple[str, str] | None:
    """The (label, data) of the one link button a reply with views gets on Telegram: the
    focus view's page. None without views or the web app's origin. No cards there."""
    focus = next((v for v in views if v.focus), None)
    link = app_link(origin, CATALOG[focus.kind].path) if focus else None
    return (OPEN_IN_NEXUS, link) if link else None
