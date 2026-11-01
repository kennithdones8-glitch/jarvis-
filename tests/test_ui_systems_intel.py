"""Systems in three parts; Briefing & ideas as a read-only section."""

from test_dashboard import call


def _js(d):
    return call(d, "/static/app.js")[2].decode()


def test_systems_has_health_setup_and_configuration_with_unchanged_actions(dash):
    d, _, _ = dash
    js = _js(d)
    systems = js.split("function renderSystems(d) {")[1].split("\n}\n")[0]
    assert 'part("Health")' in systems and 'part("Setup")' in systems and 'part("Configuration")' in systems
    assert "health.items.map((i) =>" in systems  # every check, not only the failing ones
    for request in ("`/api/devices/${x.id}/revoke`", "`/api/touchid/${k.id}/remove`", 'api("/api/logout", {})'):
        assert systems.count(request) == 1, request


def test_briefing_and_ideas_only_read(dash):
    d, _, _ = dash
    js = _js(d)
    intel = js.split("async function loadIntel() {")[1].split("\n}\n")[0]
    assert 'api("/api/briefing")' in intel and 'api("/api/proposals")' in intel
    assert "/approve" not in intel and "/reject" not in intel and "call(" not in intel  # deciding stays on the Ideas page
    assert "sections.flat(Infinity)" in intel
    assert '"intelligence"' in js.split("const VIEWS =")[1].split("\n")[0]


def test_navigation_points_to_briefing_and_ideas_everywhere(dash):
    d, _, _ = dash
    assert 'href="#/intelligence" data-view="intelligence"' in call(d, "/")[2].decode()
    for page in ("/bench", "/trust", "/proposals"):
        assert 'href="/#/intelligence"' in call(d, page)[2].decode(), page
    assert call(d, "/proposals")[0] == 200  # the old Ideas page still works
