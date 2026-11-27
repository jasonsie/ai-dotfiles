"""The install steps, as one ordered list.

Install runs them in this order, uninstall in reverse, the healthcheck asks each one for its
checks, and --help lists them. Adding a step is one module in this folder and one line here.

A step module keeps its own main() (`python3 lib/install/<step>.py --help` works) and adds:

  SUMMARY      one line for install's --help
  UNDO         one line for uninstall's --help
  CLOUD_SKIP   the line printed in place of the step in a cloud session; absent when the step runs there
  execute(options)  the step's run, as `run.py` calls it; returns the number of changes
  checks(options)   optional: the healthcheck's lines, a list of (status, message) where status
                    is ok, FAIL, skip or info (read-only: it measures the live state)
  CHECKS_TITLE      optional: the heading over those lines, where the step's name alone says too little
"""
from dataclasses import dataclass
import importlib
from pathlib import Path
from types import ModuleType

STEPS = ('instructions', 'settings', 'mcp', 'skills', 'plugins', 'hooks', 'launchd')
STATUSES = ('ok', 'FAIL', 'skip', 'info')


@dataclass(frozen=True)
class Options:
    """What a run asks of every step."""
    home: Path
    target: str = 'all'  # a CLI listed in config/ai-clis.json, or all
    apply: bool = False  # false is a dry run
    uninstall: bool = False
    cloud: bool = False  # a cloud session's VM
    live: Path | None = None  # installer.live_root: the checkout the live setup runs from
    replace_instructions: bool = False


def load(names=STEPS) -> list[ModuleType]:
    """The step modules, in order; the folder of this file is on sys.path when it runs."""
    return [importlib.import_module(name) for name in names]
