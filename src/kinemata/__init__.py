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
