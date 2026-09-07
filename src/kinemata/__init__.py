"""A general registry contract: one declared place, single source of truth."""

from .contract import BaseRegistry, Entry, Registry, undeclared
from .projection import BudgetViolation, Projection, project

# Grouped by source module, mirroring the imports above and the `__all__ +=`
# blocks below. Sorting only this list would leave one block ordered one way
# and four the other.
__all__ = [  # noqa: RUF022
    "BaseRegistry",
    "Entry",
    "Registry",
    "undeclared",
    "Projection",
    "BudgetViolation",
    "project",
]

from .bypass import Bypass, scan, unused

__all__ += ["Bypass", "scan", "unused"]

from .baseline import Accepted, Baseline, BaselineError, record  # noqa: E402

__all__ += ["Accepted", "Baseline", "BaselineError", "record"]

from .gates import Gate, Inventory, enforced  # noqa: E402

__all__ += ["Gate", "Inventory", "enforced"]

from .context import Loaded, Measurement, measure  # noqa: E402

__all__ += ["Loaded", "Measurement", "measure"]
