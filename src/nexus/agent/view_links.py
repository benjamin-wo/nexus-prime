"""The screens Prime can bring up by name, read from the view catalog (``views.CATALOG``).

``show`` (and the "Open ..." buttons on replies) look a view up here. A page moves only by
changing its path in the catalog.
"""

from dataclasses import dataclass

from nexus.agent.views import CATALOG


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
