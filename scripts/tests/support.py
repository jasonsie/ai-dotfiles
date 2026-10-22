"""Load the repo's scripts in tests by path (some names have hyphens); steps import installer."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/install'))


def load(script):
    """The module in scripts/<script>, e.g. load('install/skills.py')."""
    path = ROOT / 'scripts' / script
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry(folder, **switches):
    """A copy of config/ai-clis.json in `folder` with some CLIs switched, e.g. agy=False."""
    data = json.loads((ROOT / 'config/ai-clis.json').read_text())
    for cli, on in switches.items():
        data['clis'][cli]['on'] = on
    path = Path(folder) / 'ai-clis.json'
    path.write_text(json.dumps(data, indent=2))
    return path


def where(cli, kind):
    """A CLI's path for one kind of file, relative to the home folder (config/ai-clis.json)."""
    return json.loads((ROOT / 'config/ai-clis.json').read_text())['clis'][cli][kind][2:]


CLIS = tuple(json.loads((ROOT / 'config/ai-clis.json').read_text())['clis'])
