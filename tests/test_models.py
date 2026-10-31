from pathlib import Path

import pytest

from model_servers import start_ollama, start_openai

from jarvis.core.killswitch import EmergencyStop
from jarvis.core.tools import ApprovalRequired
from jarvis.models import (
    BudgetExceeded, Category, ChatRequest, EgressDenied, Message, Need, NoModelAvailable, parse_json_output,
)
from jarvis.models.config import ConfigError, load_model_config, parse_model_config
from jarvis.models.providers import OllamaProvider, OpenAICompatProvider
from jarvis.models.secrets import EnvSecrets
from jarvis.models.types import InvalidModelOutput, ProviderUnavailable

KEY = "test-key-123"
MARKER = "PRIVATE-MARKER-7f3a"


class DictSecrets:
    def __init__(self, **values):
        self.values = values

    def get(self, name):
        return self.values.get(name)


def model_block(mid, quality, speed, caps='["chat","plan","summarize","json"]', cin=0.0, cout=0.0, ctx=16384):
    return (f'id = "{mid}"\ncapabilities = {caps}\ncontext_tokens = {ctx}\nquality = {quality}\nspeed = {speed}\n'
            f'input_cost_per_mtok = {cin}\noutput_cost_per_mtok = {cout}\n')


@pytest.fixture
def servers():
    started = []

    def _start(kind, **kw):
        s = start_ollama(**kw) if kind == "ollama" else start_openai(KEY)
        started.append(s)
        return s
    yield _start
    for s in started:
        s.stop()


@pytest.fixture
def model_kernel(make_kernel, tmp_path, servers):
    """Kernel with one local model (quality 2) and one enabled free cloud model (quality 4)."""
    def _make(*, local_installed=("small:3b",), cloud=True, budget=0.0, cloud_cost=0.0, local_only="[]",
              extra_local=""):
        ollama = servers("ollama", installed=list(local_installed))
        openai = servers("openai")
        cfg = (f"[budget]\nmonthly_limit_usd = {budget}\n[privacy]\nlocal_only_categories = {local_only}\n"
               f'[providers.ollama]\nkind = "ollama"\nenabled = true\nhost = "{ollama.url}"\n'
               f"[[providers.ollama.models]]\n{model_block('small:3b', 2, 4)}{extra_local}"
               f'[providers.cloud]\nkind = "openai_compat"\nenabled = {str(cloud).lower()}\n'
               f'base_url = "{openai.url}"\napi_key_secret = "cloud_key"\ndata_use_note = "test provider"\n'
               f"[[providers.cloud.models]]\n{model_block('big-70b', 4, 5, cin=cloud_cost, cout=cloud_cost)}")
        (tmp_path / "jarvis.toml").write_text(cfg)
        k = make_kernel(config_path=tmp_path / "jarvis.toml", secrets=DictSecrets(cloud_key=KEY))
        return k, ollama, openai
    return _make


def req(*msgs, max_tokens=256, json_mode=False):
    return ChatRequest(tuple(msgs), max_tokens=max_tokens, json_mode=json_mode)


SYSTEM = Message("system", "You are JARVIS.", Category.SYSTEM_PROMPT)


# ---- adapters ------------------------------------------------------------------------------
def test_ollama_adapter_wire_format(servers):
    s = servers("ollama", installed=["small:3b", "other:1b"])
    s.reply = lambda body: '{"answer": 42}'
    p = OllamaProvider("ollama", s.url, {"small:3b": parse_model_config({"providers": {"o": {
        "kind": "ollama", "models": [{"id": "small:3b", "capabilities": ["chat"], "context_tokens": 4096,
                                      "quality": 2, "speed": 4}]}}}).providers[0].models["small:3b"]})
    assert p.available_models() == {"small:3b"}  # configured AND installed only
    r = p.chat("small:3b", req(Message("user", "hi"), json_mode=True, max_tokens=50))
    assert parse_json_output(r.text, ("answer",)) == {"answer": 42}
    assert (r.usage.input_tokens, r.usage.output_tokens) == (11, 7)
    body = s.received[0]["body"]
    assert body["format"] == "json" and body["stream"] is False and body["options"]["num_predict"] == 50


def test_local_provider_must_be_loopback():
    for host in ("http://10.0.0.5:11434", "http://example.com:11434", "http://169.254.169.254"):
        with pytest.raises(ValueError):
            OllamaProvider("ollama", host, {})


def test_cloud_provider_requires_https_and_key():
    with pytest.raises(ValueError):
        OpenAICompatProvider("c", "http://api.example.com/v1", {}, api_key_secret="k", secrets=EnvSecrets())
    p = OpenAICompatProvider("c", "https://api.example.com/v1", {}, api_key_secret="missing", secrets=DictSecrets())
    with pytest.raises(ProviderUnavailable, match="no API key"):
        p.available_models()


def test_ollama_down_is_unavailable_not_crash():
    p = OllamaProvider("ollama", "http://127.0.0.1:9", {})
    with pytest.raises(ProviderUnavailable):
        p.available_models()


# ---- routing -------------------------------------------------------------------------------
def test_routes_simple_work_locally(model_kernel):
    k, ollama, openai = model_kernel()
    r = k.models.complete(Need("chat"), req(SYSTEM, Message("user", "hello")), purpose="test")
    assert r.provider == "ollama" and len(ollama.received) == 1 and openai.received == []


def test_quality_floor_selects_cloud_but_private_data_needs_approval(model_kernel):
    k, ollama, openai = model_kernel()
    with pytest.raises(ApprovalRequired) as ei:
        k.models.complete(Need("plan", min_quality=4), req(SYSTEM, Message("user", MARKER)), purpose="plan",
                          task_id="t1")
    assert openai.received == []
    appr = k.approvals.get(ei.value.approval_id)
    assert appr["tool"] == "egress" and appr["action"] == "cloud" and appr["resource"] == "conversation"
    assert "test provider" in appr["summary"] and "free" in appr["summary"]


def test_local_only_data_never_routes_to_cloud(model_kernel):
    k, ollama, openai = model_kernel()
    with pytest.raises(NoModelAvailable) as ei:
        k.models.complete(Need("plan", min_quality=4),
                          req(Message("user", MARKER, local_only=True)), purpose="test")
    assert "local-only" in ei.value.reasons["cloud/big-70b"]
    assert openai.received == [] and ollama.received == []


def test_unavailable_models_reported_with_reasons(model_kernel):
    k, *_ = model_kernel(local_installed=())
    with pytest.raises(NoModelAvailable) as ei:
        k.models.complete(Need("code"), req(Message("user", "x")), purpose="test")
    assert "ollama/small:3b" in ei.value.reasons and "cloud/big-70b" in ei.value.reasons


def test_paid_model_excluded_under_zero_budget(model_kernel):
    k, ollama, openai = model_kernel(cloud_cost=5.0)
    with pytest.raises(NoModelAvailable) as ei:
        k.models.complete(Need("plan", min_quality=4), req(SYSTEM), purpose="test")
    assert ei.value.reasons["cloud/big-70b"] == "would exceed budget"
    assert openai.received == []


def test_local_failure_falls_back_but_never_silently_sends_private_data(model_kernel):
    k, ollama, openai = model_kernel()
    ollama.fail_status = 500
    with pytest.raises(ApprovalRequired):
        k.models.complete(Need("chat"), req(Message("user", MARKER)), purpose="test", task_id="t1")
    assert openai.received == []


def test_fallback_between_local_models(model_kernel):
    extra = f"[[providers.ollama.models]]\n{model_block('alt:1b', 1, 5)}"
    k, ollama, _ = model_kernel(local_installed=("small:3b", "alt:1b"), cloud=False, extra_local=extra)
    calls = []

    def reply(body):
        calls.append(body["model"])
        if body["model"] == "small:3b":
            raise RuntimeError("boom")  # handler crash -> HTTP 500-ish connection error
        return "from alt"
    ollama.reply = reply
    r = k.models.complete(Need("chat"), req(Message("user", "hi")), purpose="test")
    assert r.model == "alt:1b" and calls[0] == "small:3b"


# ---- egress gate ---------------------------------------------------------------------------
def gate_of(k):
    return k.models.router.gate


def test_public_only_request_sends_without_approval(model_kernel):
    k, _, openai = model_kernel()
    r = gate_of(k).send("cloud", "big-70b", req(SYSTEM, Message("user", "page text", Category.WEB_CONTENT)),
                        purpose="summarise public page")
    assert r.text == "ok" and openai.received[0]["auth"] == f"Bearer {KEY}"


def test_approval_is_bound_to_exact_request(model_kernel):
    k, _, openai = model_kernel()
    g = gate_of(k)
    private = req(Message("user", MARKER))
    with pytest.raises(ApprovalRequired) as ei:
        g.send("cloud", "big-70b", private, purpose="p", task_id="t1")
    k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")
    with pytest.raises(ApprovalRequired):
        g.send("cloud", "big-70b", req(Message("user", MARKER + " plus extra secrets")), purpose="p", task_id="t1")
    assert openai.received == []
    g.send("cloud", "big-70b", private, purpose="p", task_id="t1")
    assert len(openai.received) == 1
    with pytest.raises(ApprovalRequired):  # single use
        g.send("cloud", "big-70b", private, purpose="p", task_id="t1")


def test_rejected_transmission_stays_rejected(model_kernel):
    k, _, openai = model_kernel()
    g = gate_of(k)
    with pytest.raises(ApprovalRequired) as ei:
        g.send("cloud", "big-70b", req(Message("user", MARKER)), purpose="p", task_id="t1")
    k.approvals.decide(ei.value.approval_id, approve=False, by="user:test")
    with pytest.raises(EgressDenied, match="rejected"):
        g.send("cloud", "big-70b", req(Message("user", "different text")), purpose="p", task_id="t1")
    assert openai.received == []


def test_standing_grant_and_revocation(model_kernel):
    k, _, openai = model_kernel()
    g = gate_of(k)
    with pytest.raises(PermissionError):
        g.grants.grant(category="file_content", provider="cloud", by="model")
    gid = g.grants.grant(category="file_content", provider="cloud", by="user:test")
    g.send("cloud", "big-70b", req(Message("user", "file text", Category.FILE_CONTENT)), purpose="p")
    assert len(openai.received) == 1
    with pytest.raises(ApprovalRequired):  # a grant for files does not cover conversation
        g.send("cloud", "big-70b", req(Message("user", "x", Category.FILE_CONTENT), Message("user", "y")),
               purpose="p")
    g.grants.revoke(gid, by="user:test")
    with pytest.raises(ApprovalRequired):
        g.send("cloud", "big-70b", req(Message("user", "file text", Category.FILE_CONTENT)), purpose="p")
    assert len(openai.received) == 1


def test_configured_local_only_category_blocked_even_with_grant(model_kernel):
    k, _, openai = model_kernel(local_only='["memory"]')
    g = gate_of(k)
    g.grants.grant(category="memory", provider="cloud", by="user:test")
    with pytest.raises(EgressDenied, match="local-only"):
        g.send("cloud", "big-70b", req(Message("user", MARKER, Category.MEMORY)), purpose="p")
    assert openai.received == []


def test_secret_content_blocked(model_kernel):
    k, _, openai = model_kernel()
    with pytest.raises(EgressDenied, match="secret"):
        gate_of(k).send("cloud", "big-70b", req(Message("user", "key sk-ant-abcdefghijklmnopqrstu", Category.WEB_CONTENT)),
                        purpose="p")
    assert openai.received == []


def test_budget_guard_blocks_and_records(model_kernel):
    k, _, openai = model_kernel(cloud_cost=10.0)  # $10 per Mtok
    g = gate_of(k)
    with pytest.raises(BudgetExceeded):
        g.send("cloud", "big-70b", req(SYSTEM), purpose="p")
    assert openai.received == []
    g.budget.monthly_limit_usd = 1.0  # as if the user approved a $1 budget
    g.send("cloud", "big-70b", req(SYSTEM), purpose="p")
    assert g.budget.spent_this_month() == pytest.approx((1000 + 500) * 10 / 1e6)


def test_unknown_or_disabled_provider_denied(model_kernel):
    k, _, openai = model_kernel(cloud=False)
    with pytest.raises(EgressDenied):
        gate_of(k).send("cloud", "big-70b", req(SYSTEM), purpose="p")
    assert openai.received == []


def test_emergency_stop_blocks_model_calls(model_kernel):
    k, ollama, openai = model_kernel()
    k.killswitch.engage(by="user:test", reason="t")
    with pytest.raises(EmergencyStop):
        k.models.complete(Need("chat"), req(SYSTEM), purpose="p")
    with pytest.raises(EmergencyStop):
        gate_of(k).send("cloud", "big-70b", req(SYSTEM), purpose="p")
    assert ollama.received == [] and openai.received == []


def test_audit_never_contains_message_content(model_kernel):
    k, _, _ = model_kernel()
    g = gate_of(k)
    g.grants.grant(category="conversation", provider="cloud", by="user:test")
    g.send("cloud", "big-70b", req(Message("user", MARKER)), purpose="p")
    k.models.complete(Need("chat"), req(Message("user", MARKER)), purpose="p")
    blob = str(k.audit.entries(limit=1000))
    assert MARKER not in blob and KEY not in blob
    events = [e["event"] for e in k.audit.entries(limit=1000)]
    assert {"egress.send", "egress.received", "model.route", "model.local_call"} <= set(events)
    assert k.audit.verify().ok


def test_config_file_is_protected_from_tools(model_kernel, tmp_path, root):
    k, *_ = model_kernel()
    assert any(p == (tmp_path / "jarvis.toml").resolve() for p in k.policy.protected)


# ---- config & output validation ------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"oops": {}},
    {"budget": {"monthly_limit_usd": -1}},
    {"privacy": {"local_only_categories": ["passwords"]}},
    {"providers": {"x": {"kind": "magic"}}},
    {"providers": {"x": {"kind": "openai_compat", "base_url": "https://a"}}},
    {"providers": {"x": {"kind": "ollama", "models": [{"id": "m", "capabilities": ["telepathy"],
                                                         "context_tokens": 1, "quality": 1, "speed": 1}]}}},
    {"providers": {"x": {"kind": "ollama", "models": [{"id": "m", "capabilities": ["chat"],
                                                         "context_tokens": 1, "quality": 9, "speed": 1}]}}},
])
def test_invalid_model_config_rejected(bad):
    with pytest.raises(ConfigError):
        parse_model_config(bad)


def test_example_config_parses_with_cloud_disabled_and_zero_budget():
    cfg = load_model_config(Path(__file__).parents[1] / "config" / "jarvis.example.toml")
    assert cfg.monthly_limit_usd == 0.0
    assert [p.name for p in cfg.providers if p.enabled] == ["ollama"]


def test_parse_json_output_validation():
    assert parse_json_output('```json\n{"a": 1}\n```', ("a",)) == {"a": 1}
    for bad in ("not json", "[1,2]", '{"b": 1}'):
        with pytest.raises(InvalidModelOutput):
            parse_json_output(bad, ("a",))
