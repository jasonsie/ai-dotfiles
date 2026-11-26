"""adapters: what differs between the CLIs on the hook side, one adapter per CLI.

  get(cli)    the adapter of a CLI id (config/ai-clis.json); an unknown id gets one that knows nothing
  CLIS        the ids that have one

A feature does not name a CLI: tests/test_rules.py fails when one does. The Event a feature receives
(scripts/agent_hooks.py) gives it the command, its folder and the files a call names; what else a CLI
can do is a named capability of its adapter. Python 3.11+, stdlib only.
"""
from .agy import Antigravity
from .base import Adapter
from .claude import Claude
from .codex import Codex
from .pi import Pi

ADAPTERS = {adapter.cli: adapter for adapter in (Claude(), Codex(), Antigravity(), Pi())}
CLIS = tuple(ADAPTERS)
UNKNOWN = Adapter()


def get(cli):
    return ADAPTERS.get(cli, UNKNOWN)
