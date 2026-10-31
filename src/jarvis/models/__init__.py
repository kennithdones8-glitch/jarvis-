"""Model layer: local/cloud providers, router, egress privacy gate, budget guard."""

from __future__ import annotations

from ..core.approvals import Approvals
from ..core.audit import AuditLog
from ..core.db import Database
from ..core.killswitch import KillSwitch
from .config import ModelConfig, load_model_config
from .egress import BudgetExceeded, BudgetGuard, EgressDenied, EgressGate, SensitivityPolicy
from .providers import ClaudeCodeProvider, OllamaProvider, OpenAICompatProvider
from .router import ModelRouter, ModelService, Need, NoModelAvailable
from .secrets import SecretStore, default_secrets
from .types import Category, ChatRequest, ChatResponse, Message, ModelInfo, parse_json_output


def build_model_service(config: ModelConfig, db: Database, audit: AuditLog, approvals: Approvals,
                        killswitch: KillSwitch, *, secrets: SecretStore | None = None,
                        workdir: str | None = None) -> ModelService:
    secrets = secrets or default_secrets()
    local, cloud = [], []
    for pc in config.providers:
        if not pc.enabled:
            continue
        if pc.kind == "ollama":
            local.append(OllamaProvider(pc.name, pc.host or "http://127.0.0.1:11434", pc.models))
        elif pc.kind == "claude_code":
            if workdir is None:
                raise ValueError("Claude Code provider needs a working directory")
            claude = ClaudeCodeProvider(pc.name, pc.models, workdir=workdir, command=pc.command,
                                        data_use_note=pc.data_use_note)
            claude.cancel_check = killswitch.engaged
            cloud.append(claude)
        else:
            cloud.append(OpenAICompatProvider(pc.name, pc.base_url, pc.models, api_key_secret=pc.api_key_secret,
                                              secrets=secrets, data_use_note=pc.data_use_note))
    gate = EgressGate(db, audit, approvals, killswitch, cloud,
                      sensitivity=SensitivityPolicy(local_only=config.local_only_categories),
                      budget=BudgetGuard(db, monthly_limit_usd=config.monthly_limit_usd))
    return ModelService(ModelRouter(local, gate, mode=config.routing_mode), audit, killswitch)


__all__ = [
    "BudgetExceeded", "Category", "ChatRequest", "ChatResponse", "EgressDenied", "Message", "ModelConfig",
    "ModelInfo", "ModelService", "Need", "NoModelAvailable", "build_model_service", "load_model_config",
    "parse_json_output",
]
