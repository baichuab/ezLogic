"""Hosting helpers in main.py: serving the built frontend, and SSE keep-alives."""

import asyncio

import httpx
from fastapi import FastAPI

import main


def _site(tmp_path):
    (tmp_path / "_app" / "immutable").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<html>shell</html>")
    (tmp_path / "robots.txt").write_text("User-agent: *")
    (tmp_path / "_app" / "immutable" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")

    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    assert main.mount_site(app, tmp_path)
    return app


def _get(app, *paths):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [await client.get(p) for p in paths]
    return asyncio.run(go())


def test_site_serves_files_spa_fallback_and_leaves_api_alone(tmp_path):
    root, page, robots, asset, api, missing_api, escape = _get(
        _site(tmp_path),
        "/", "/chat/123", "/robots.txt", "/_app/immutable/app.js",
        "/api/ping", "/api/nope", "/../secret.txt",
    )
    assert root.text == page.text == "<html>shell</html>"
    assert page.headers["cache-control"] == "no-cache"
    assert robots.text == "User-agent: *"
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert api.json() == {"ok": True}
    assert missing_api.status_code == 404 and missing_api.json() == {"detail": "Not Found"}
    assert escape.text == "<html>shell</html>"  # never a file outside the build


def test_site_is_not_mounted_without_a_build(tmp_path):
    app = FastAPI()
    assert main.mount_site(app, tmp_path) is False
    assert _get(app, "/")[0].status_code == 404


def test_keepalive_fills_quiet_gaps_and_keeps_order():
    async def slow():
        yield "data: 1\n\n"
        await asyncio.sleep(0.25)
        yield "data: 2\n\n"

    async def go():
        return [c async for c in main._with_keepalive(slow(), interval=0.1)]

    out = asyncio.run(go())
    assert out[0] == "data: 1\n\n" and out[-1] == "data: 2\n\n"
    assert out[1:-1] and set(out[1:-1]) == {main.KEEPALIVE}


def test_keepalive_reraises_and_cancels_the_body():
    cancelled = asyncio.Event()

    async def failing():
        yield "data: 1\n\n"
        raise RuntimeError("boom")

    async def endless():
        try:
            while True:
                yield "data: x\n\n"
                await asyncio.sleep(0.01)
        finally:
            cancelled.set()

    async def go():
        stream = main._with_keepalive(failing(), interval=5)
        assert await stream.__anext__() == "data: 1\n\n"
        try:
            await stream.__anext__()
        except RuntimeError as e:
            failed = str(e)
        stream = main._with_keepalive(endless(), interval=5)
        await stream.__anext__()
        await stream.aclose()  # the client disconnected
        await asyncio.sleep(0)
        return failed, cancelled.is_set()

    assert asyncio.run(go()) == ("boom", True)
