"""Stay signed in: off by default (the sign-in ends when the browser quits). Only you can turn it on, on the Mac, with
Touch ID when set up; then this browser's cookie lasts 30 days. It is still HttpOnly and same-site, and the Touch ID
gates are untouched."""

import json
import re

from test_dashboard import call


def _cookie(headers):
    return next(v for k, v in headers.items() if k.lower() == "set-cookie")


def test_off_by_default_the_cookie_ends_with_the_browser(dash):
    d, *_ = dash
    status, headers, _ = call(d, "/?token=test-token", cookie=False)
    assert status == 303 and "Max-Age" not in _cookie(headers)
    assert json.loads(call(d, "/api/state")[2])["stay_signed_in"]["on"] is False


def test_turning_it_on_reissues_a_30_day_cookie_and_off_takes_it_back(dash):
    d, *_ = dash
    status, headers, body = call(d, "/api/settings/stay-signed-in", {"on": True})
    c = _cookie(headers)
    assert status == 200 and "Max-Age=2592000" in c and "HttpOnly" in c and "SameSite=Strict" in c
    assert json.loads(body)["url"] == f"http://localhost:{d.port}/"
    assert "Max-Age" in _cookie(call(d, "/?token=test-token", cookie=False)[1])
    assert any(e["event"] == "signin.stay_signed_in" for e in d.kernel.audit.entries(limit=20))
    assert "Max-Age" not in _cookie(call(d, "/api/settings/stay-signed-in", {"on": False})[1])
    assert call(d, "/api/settings/stay-signed-in", {"on": "yes"})[0] == 400
    assert call(d, "/api/settings/stay-signed-in", {"on": True}, cookie=False)[0] == 401     # never without signing in


def test_mac_only_and_touch_id():
    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    assert any(re.fullmatch(p, "/api/settings/stay-signed-in") for p in LOCAL_ONLY)
    assert any(re.fullmatch(p, "/api/settings/stay-signed-in") for p in MAC_STEP_UP)


def test_start_up_assembly_plays_once_a_day_so_the_page_opens_at_once(dash):
    d, *_ = dash
    js = call(d, "/static/app.js")[2].decode()
    assert 'if (localStorage.getItem("jarvis-boot-day") === today) sessionStorage.setItem("jarvis-booted", "1");' in js
    assert js.index("jarvis-boot-day") < js.index("JarvisAvatar.mount(")     # decided before the projection mounts
