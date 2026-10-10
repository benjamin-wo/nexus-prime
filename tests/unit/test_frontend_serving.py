from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.channels.web.frontend import mount_frontend


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
    assert "x-robots-tag" not in client.get("/ledger").headers
