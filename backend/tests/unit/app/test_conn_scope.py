"""Every database connection commits before the response is sent (review fix, Day 5).

FastAPI ends ``yield`` dependencies after the response by default, so a client could get the
login answer and call ``/me`` before the new session was committed (seen as a flaky E2E 401).
``Depends(get_conn, scope="function")`` commits first; this test keeps every route that way.
"""

from api_support import make_app
from fastapi.routing import APIRoute

from tradelens.core.deps import get_conn


def walk(dependant):
    yield dependant
    for sub in dependant.dependencies:
        yield from walk(sub)


def routes(items):
    """Every route, also inside included routers (FastAPI keeps them nested)."""
    for item in items:
        inner = getattr(item, "original_router", None)
        if inner is not None:
            yield from routes(inner.routes)
        else:
            yield item


def test_every_get_conn_dependency_commits_before_the_response():
    app, _, _ = make_app(engine=None)
    found, wrong = 0, []
    for route in routes(app.routes):
        if not isinstance(route, APIRoute):
            continue
        for dep in walk(route.dependant):
            if dep.call is get_conn:
                found += 1
                if dep.scope != "function":
                    wrong.append(route.path)
    assert found > 10
    assert wrong == []


def test_thread_limit_matches_pool_capacity():
    """Load-check fix: threads never outnumber database connections (no pool deadlock)."""
    from fastapi.testclient import TestClient

    from tradelens.app.bootstrap import API_THREADS, DB_POOL_OVERFLOW, DB_POOL_SIZE

    app, _, _ = make_app(engine=None)
    with TestClient(app):
        assert app.state.thread_tokens == API_THREADS
    assert API_THREADS <= DB_POOL_SIZE + DB_POOL_OVERFLOW
