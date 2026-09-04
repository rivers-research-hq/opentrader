"""MoT — Model of Traders coordinator."""
from .coordinator import MoTCoordinator, MoTState, CARTOGRAPHER_NAMES, REVIEW_HOURS
from .scoring import AgentScorer, AgentRecord
from .reflection import ReflectionLog
from .agents import DebateEngine, DebateResult, AdirDebateEngine
from .adapter_registry import AdapterRegistry, AdapterRecord

# Heavy modules (torch, GPU init) are loaded lazily via __getattr__
# to keep harness→llama-swap fast path lightweight.

_HEAVY = {
    "FineTunedAgent": ".finetuned_agent",
    "ModelPool": ".pool",
    "TrainingCoach": ".coach",
    "Ensemble": ".ensemble",
    "ATDL": ".lifecycle",
    "Phase": ".lifecycle",
    "PHASE_LABELS": ".lifecycle",
}


def __getattr__(name: str):
    if name in _HEAVY:
        import importlib
        mod = importlib.import_module(_HEAVY[name], __package__)
        attr = getattr(mod, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MoTCoordinator", "MoTState", "CARTOGRAPHER_NAMES", "REVIEW_HOURS",
    "AgentScorer", "AgentRecord",
    "ReflectionLog",
    "DebateEngine", "DebateResult", "AdirDebateEngine",
    "AdapterRegistry", "AdapterRecord",
    "FineTunedAgent",
    "ModelPool",
    "TrainingCoach",
    "Ensemble",
    "ATDL", "Phase", "PHASE_LABELS",
]
