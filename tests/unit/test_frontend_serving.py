from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.channels.web.frontend import mount_frontend
from nexus.channels.web.travel_api import map_key
from nexus.settings import Settings


def build(tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("nope")
    app = FastAPI()

    @app.get("/api/real")
    def real() -> dict[str, bool]:
        return {"ok": True}

    mount_frontend(app, tmp_path)
    return TestClient(app)


def test_client_routes_get_the_app(tmp_path: Path) -> None:
    client = build(tmp_path)
    for path in ("/", "/ledger", "/invite/abc"):
        response = client.get(path)
        assert response.text == "<html>app</html>"
        assert response.headers["cache-control"] == "no-cache"
        assert "default-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"


def test_backend_paths_and_traversal_are_not_served(tmp_path: Path) -> None:
    client = build(tmp_path)
    assert client.get("/api/real").json() == {"ok": True}
    assert client.get("/api/missing").status_code == 404
    assert client.get("/telegram/anything").status_code == 404
    assert "nope" not in client.get("/../secret.txt").text
    assert "nope" not in client.get("/%2e%2e/secret.txt").text


def test_api_only_without_a_build(tmp_path: Path) -> None:
    app = FastAPI()
    mount_frontend(app, tmp_path / "missing")
    assert TestClient(app).get("/ledger").status_code == 404


def test_shared_trip_links_ask_search_engines_not_to_index_them(tmp_path: Path) -> None:
    client = build(tmp_path)
    shared = client.get("/shared/" + "a" * 43)
    assert shared.text == "<html>app</html>"
    assert shared.headers["x-robots-tag"] == "noindex, nofollow"
    assert shared.headers["referrer-policy"] == "same-origin"
    ledger = client.get("/ledger")
    assert "x-robots-tag" not in ledger.headers
    # The rest of the app sends its origin (never a path) to other sites, which the
    # map's key needs; the shared link above sends nothing.
    assert ledger.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_the_trip_map_is_allowed_and_nothing_else_is(tmp_path: Path) -> None:
    csp = build(tmp_path).get("/travel").headers["content-security-policy"]
    rules = dict(rule.split(" ", 1) for rule in csp.split("; "))
    assert rules["script-src"] == "'self' https://telegram.org https://maps.googleapis.com"
    assert "'unsafe-inline'" not in rules["script-src"] and "'unsafe-eval'" not in csp
    assert rules["style-src"] == "'self' 'unsafe-inline' https://fonts.googleapis.com"
    assert "https://*.gstatic.com" in rules["img-src"]
    assert rules["frame-ancestors"] == "https://web.telegram.org"


def test_the_page_never_gets_the_server_key() -> None:
    def settings(**keys: str) -> Settings:
        return Settings(_env_file=None, database_url="postgresql://u:p@h/db", **keys)  # type: ignore[arg-type]

    # Made-up keys. The browser's own key is handed to the page...
    both = settings(google_places_api_key="server-key-0001", google_maps_browser_key="browser-0001")
    assert map_key(both) == "browser-0001"
    # ...but the server's key never is, even when it's set as the browser key too.
    key = "server-key-0001"
    assert map_key(settings(google_places_api_key=key, google_maps_browser_key=key)) is None
    assert map_key(settings(google_places_api_key=key)) is None
