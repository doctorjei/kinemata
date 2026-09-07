"""A general registry contract: one declared place, single source of truth."""

from .contract import BaseRegistry, Entry, Registry, undeclared
from .projection import BudgetViolation, Projection, project

__all__ = [
    "BaseRegistry",
    "Entry",
    "Registry",
    "undeclared",
    "Projection",
    "BudgetViolation",
    "project",
]

from .bypass import Bypass, scan, unused  # noqa: E402

__all__ += ["Bypass", "scan", "unused"]

from .baseline import Accepted, Baseline, BaselineError, record  # noqa: E402

__all__ += ["Accepted", "Baseline", "BaselineError", "record"]

from .gates import Gate, Inventory, enforced  # noqa: E402

__all__ += ["Gate", "Inventory", "enforced"]
