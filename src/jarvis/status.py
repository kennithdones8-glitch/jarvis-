"""Status snapshots shared by the CLI and the dashboard."""

from __future__ import annotations

from .core import Kernel
from .models.types import ProviderError


def models_status(kernel: Kernel) -> dict:
    router = kernel.models.router
    out = {"budget": {"monthly_limit_usd": router.gate.budget.monthly_limit_usd,
                      "spent_this_month_usd": router.gate.budget.spent_this_month()},
           "local_only_categories": list(kernel.model_config.local_only_categories), "providers": []}
    sources = [(p.name, "local", p.models, p.available_models, p.data_use_note) for p in router.local.values()]
    sources += [(s.name, "cloud", s.models, lambda n=s.name: router.gate.available_models(n), s.data_use_note)
                for s in router.gate.summaries()]
    for name, location, models, available_fn, note in sources:
        try:
            available, error = sorted(available_fn()), None
        except ProviderError as exc:
            available, error = [], str(exc)
        out["providers"].append({"name": name, "location": location, "configured": sorted(models),
                                 "available": available, "error": error, "data_use": note})
    out["routing_mode"] = router.mode
    out["cloud_usage"] = router.gate.usage_summary()
    disabled = [p.name for p in kernel.model_config.providers if not p.enabled]
    out["disabled_providers"] = disabled
    return out
