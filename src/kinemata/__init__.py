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

# Last, and deliberately so: `access` pulls in `config`, which reaches every
# adapter, and one of those reaches back through this package for `stamps`.
# Placing it after the blocks above means the names they publish are bound
# before that round trip starts.
#
# The run-time surface -- what an adopting project's own test suite imports to
# assert against a declaration while its code runs. Small on purpose; see
# `access` for the boundary it complements and for what it is not.
from .access import UnknownRegistry, registry  # noqa: E402

__all__ += ["UnknownRegistry", "registry"]

# Re-exported so an adopter's fixture has a stable import path for the whole
# gesture -- locate a config, load it, name the failure -- without reaching
# into a submodule that is free to move.
from .config import ConfigError, Settings, find_config, load  # noqa: E402

__all__ += ["ConfigError", "Settings", "find_config", "load"]
