import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('facts', ROOT / 'skills/onboard/facts.py')
facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(facts)

SECTIONS = ['# Repo facts:', '## Languages', '## Manifests', '## Entry points', '## Tree', '## Docs']


def write(base, rel, text='', mode=None):
    path = Path(base) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


def snapshot(base):
    snap = {}
    for p in sorted(Path(base).rglob('*')):
        st = p.stat()
        snap[p.relative_to(base).as_posix()] = (st.st_mtime_ns, st.st_size if p.is_file() else 0)
    return snap


class FactsTest(unittest.TestCase):
    def run_facts(self, base):
        before = snapshot(base)
        out = facts.build(Path(base).resolve())
        self.assertEqual(snapshot(base), before, 'script must not touch the repo')
        self.assertNotIn(str(Path(base).resolve()), out)
        self.assertNotIn('/Users/', out)
        return out

    def assert_sections_in_order(self, out):
        pos = [out.index(s) for s in SECTIONS]
        self.assertEqual(pos, sorted(pos))

    def test_python_project(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'pyproject.toml', '''[project]
name = "demo"
version = "0.3.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.0", "rich"]
[project.optional-dependencies]
test = ["pytest>=8"]
[project.scripts]
demo = "demo.cli:main"
''')
            write(d, 'requirements-dev.txt', '# c\nblack==24.1\n-r other.txt\n')
            write(d, 'src/demo/__main__.py', 'print(1)\n')
            write(d, 'src/demo/cli.py', 'def main(): pass\n')
            out = self.run_facts(d)
            self.assert_sections_in_order(out)
            self.assertIn('demo 0.3.0', out)
            self.assertIn('requests >=2.0', out)
            self.assertIn('pytest >=8', out)
            self.assertIn('black ==24.1', out)
            self.assertIn('requires-python: >=3.11', out)
            self.assertIn('demo.cli:main', out)
            self.assertIn('`src/demo/__main__.py`', out)
            self.assertIn('`src/demo/cli.py`', out)
            self.assertIn('| Python | 2 |', out)

    def test_javascript_project(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'package.json', '''{"name": "web", "version": "1.2.3",
 "main": "./lib/index.js", "bin": {"web": "./bin/web.js"},
 "scripts": {"start": "node lib/index.js"},
 "dependencies": {"express": "^4.0.0"}, "devDependencies": {"vitest": "^1.0.0"}}''')
            write(d, 'lib/index.js', 'module.exports = 1\n')
            write(d, 'bin/web.js', '#!/usr/bin/env node\n')
            write(d, 'src/app.tsx', 'export {}\n')
            out = self.run_facts(d)
            self.assertIn('web 1.2.3', out)
            self.assertIn('express ^4.0.0', out)
            self.assertIn('vitest ^1.0.0', out)
            self.assertIn('`lib/index.js` — package.json "main"', out)
            self.assertIn('`bin/web.js` — package.json bin "web"', out)
            self.assertIn('- scripts: start', out)
            self.assertNotIn('scripts.start', out)
            self.assertIn('`src/app.tsx` — named app.*', out)
            self.assertIn('TypeScript (TSX)', out)

    def test_broken_package_json_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'package.json', '{nope')
            out = self.run_facts(d)
            self.assertIn('could not parse', out)

    def test_go_project(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'go.mod', '''module example.com/svc

go 1.22

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgolang.org/x/sync v0.6.0 // indirect
)
require github.com/spf13/cobra v1.8.0
''')
            write(d, 'cmd/svc/main.go', 'package main\n')
            out = self.run_facts(d)
            self.assertIn('example.com/svc', out)
            self.assertIn('github.com/gin-gonic/gin v1.9.1', out)
            self.assertIn('golang.org/x/sync v0.6.0', out)
            self.assertIn('github.com/spf13/cobra v1.8.0', out)
            self.assertIn('`cmd/svc/main.go`', out)

    def test_rust_project(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'Cargo.toml', '''[package]
name = "crab"
version = "0.1.0"
[dependencies]
serde = { version = "1", features = ["derive"] }
clap = "4"
local = { path = "../local" }
[dev-dependencies]
tempfile = "3"
''')
            write(d, 'src/main.rs', 'fn main() {}\n')
            out = self.run_facts(d)
            self.assertIn('crab 0.1.0', out)
            self.assertIn('serde 1', out)
            self.assertIn('clap 4', out)
            self.assertIn('local path ../local', out)
            self.assertIn('tempfile 3', out)
            self.assertIn('`src/main.rs`', out)
            self.assertIn('| Rust | 1 |', out)

    def test_nix_flake_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'flake.nix', '''{
  description = "my box";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
  outputs = { self, nixpkgs, ... }: { };
}
''')
            write(d, 'bootstrap.sh', '#!/bin/sh\n', mode=0o755)
            write(d, 'notes.sh', '#!/bin/sh\n', mode=0o644)
            out = self.run_facts(d)
            self.assertIn('my box', out)
            self.assertIn('nixpkgs github:NixOS/nixpkgs/nixos-24.05', out)
            self.assertIn('home-manager github:nix-community/home-manager', out)
            self.assertIn('`flake.nix` — Nix flake outputs', out)
            self.assertIn('`bootstrap.sh` — executable top-level script', out)
            self.assertNotIn('`notes.sh`', out)

    def test_executable_scripts_one_level_down(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'scripts/run.sh', '#!/bin/sh\n', mode=0o755)
            write(d, 'scripts/tool', '#!/bin/sh\n', mode=0o755)
            write(d, 'scripts/notes.sh', '#!/bin/sh\n', mode=0o644)
            write(d, 'scripts/deep/x.sh', '#!/bin/sh\n', mode=0o755)
            write(d, 'tests/check.sh', '#!/bin/sh\n', mode=0o755)
            write(d, 'spec/check.py', 'x\n', mode=0o755)
            write(d, 'top.sh', '#!/bin/sh\n', mode=0o755)
            out = self.run_facts(d)
            self.assertIn('`scripts/run.sh` — executable script in scripts/', out)
            self.assertIn('`scripts/tool` — executable script in scripts/', out)
            self.assertIn('`top.sh` — executable top-level script', out)
            self.assertNotIn('`scripts/notes.sh`', out)
            self.assertNotIn('`scripts/deep/x.sh`', out)
            self.assertNotIn('`tests/check.sh`', out)
            self.assertNotIn('`spec/check.py`', out)

    def test_package_json_targets_missing_from_repo_are_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'package.json', '''{"name": "w", "main": "dist/index.js",
 "module": "./lib/mod.js", "bin": {"w": "bin/w.js", "x": "./dist/x.js"}}''')
            write(d, 'lib/mod.js', 'x\n')
            write(d, 'bin/w.js', 'x\n')
            out = self.run_facts(d)
            self.assertIn('`dist/index.js` — package.json "main" (not in repo; built output?)', out)
            self.assertIn('`dist/x.js` — package.json bin "x" (not in repo; built output?)', out)
            self.assertIn('`lib/mod.js` — package.json "module"\n', out)
            self.assertIn('`bin/w.js` — package.json bin "w"\n', out)

    def test_cargo_bin_missing_from_repo_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'Cargo.toml', '''[package]
name = "c"
[[bin]]
name = "gone"
path = "src/bin/gone.rs"
[[bin]]
name = "here"
path = "src/bin/here.rs"
''')
            write(d, 'src/bin/here.rs', 'fn main() {}\n')
            out = self.run_facts(d)
            self.assertIn('`src/bin/gone.rs` — Cargo.toml [[bin]] "gone" (not in repo; built output?)', out)
            self.assertIn('`src/bin/here.rs` — Cargo.toml [[bin]] "here"\n', out)

    def test_package_json_scripts_are_a_note_not_entry_points(self):
        with tempfile.TemporaryDirectory() as d:
            names = [f's{i}' for i in range(10)]
            write(d, 'package.json', '{"name": "w", "scripts": {%s}}' %
                  ', '.join(f'"{n}": "echo {n}"' for n in names))
            out = self.run_facts(d)
            self.assertIn('- scripts: s0, s1, s2, s3, s4, s5, s6, s7, … +2 more', out)
            self.assertNotIn('scripts.s0', out)
            self.assertNotIn('echo s0', out)
            self.assertIn('## Entry points\n\n(none found)', out)

    def test_tree_never_drops_top_level_folders(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(80):
                write(d, f'a/sub{i:02}/f.txt', 'x\n')
            write(d, 'z/f.txt', 'x\n')
            out = self.run_facts(d)
            tree = out.split('## Tree')[1].split('## Docs')[0]
            self.assertIn('- a/ (80)', tree)
            self.assertIn('- z/ (1)', tree)
            self.assertIn('(depth 2-3 left out: too many folders)', tree)
            self.assertNotIn('a/sub00', tree)

    def test_tree_says_which_depth_was_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(80):
                write(d, f'a/b/c{i:02}/f.txt', 'x\n')
            write(d, 'z/f.txt', 'x\n')
            tree = self.run_facts(d).split('## Tree')[1].split('## Docs')[0]
            self.assertIn('(depth 3 left out: too many folders)', tree)
            self.assertIn('- a/b/ (80)', tree)
            self.assertIn('- z/ (1)', tree)
            self.assertNotIn('c00', tree)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.run_facts(d)
            self.assert_sections_in_order(out)
            self.assertIn('- files: 0', out)
            self.assertIn('git: no', out)
            self.assertIn('(none found)', out)

    def test_noise_only_directory(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'node_modules/pkg/index.js', 'x\n')
            write(d, '.venv/lib/site.py', 'x\n')
            write(d, 'node_modules/pkg/package.json', '{"name": "pkg"}')
            out = self.run_facts(d)
            self.assertIn('- files: 0', out)
            self.assertNotIn('node_modules', out)
            self.assertNotIn('.venv', out)

    def test_walk_skips_noise_next_to_real_files(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'src/a.py', 'x = 1\n')
            write(d, 'dist/bundle.js', 'x\n')
            write(d, 'target/debug/x.rs', 'x\n')
            out = self.run_facts(d)
            self.assertIn('- files: 1', out)
            self.assertNotIn('dist', out)
            self.assertNotIn('target', out)

    def test_git_repo_excludes_ignored_and_includes_untracked(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
            write(d, '.gitignore', 'secret.py\nbuild-output/\n')
            write(d, 'tracked.py', 'a = 1\n')
            write(d, 'secret.py', 'password = 1\n')
            write(d, 'build-output/x.js', 'x\n')
            subprocess.run(['git', 'add', 'tracked.py', '.gitignore'], cwd=d, check=True)
            write(d, 'untracked.py', 'b = 2\n')
            out = self.run_facts(d)
            self.assertIn('git: yes', out)
            self.assertIn('- files: 3', out)  # .gitignore, tracked.py, untracked.py
            self.assertNotIn('secret.py', out)
            self.assertNotIn('build-output', out)
            self.assertIn('| Python | 2 |', out)

    def test_subdirectory_of_git_repo_uses_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
            write(d, 'top.py', 'x\n')
            write(d, 'sub/inner/main.py', 'x\n')
            out = self.run_facts(Path(d) / 'sub')
            self.assertIn('- files: 1', out)
            self.assertIn('`inner/main.py`', out)
            self.assertNotIn('top.py', out)

    def test_report_absent(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'README.md', '# hi\n')
            out = self.run_facts(d)
            self.assertIn('- report: `.agents/onboarding.md` — absent', out)

    def test_report_generated_shows_date(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, '.agents/onboarding.md', '\ufeff<!-- Generated by onboard: 2026-10-22 -->\n# Onboarding\n')
            out = self.run_facts(d)
            self.assertIn('- report: `.agents/onboarding.md` — generated 2026-10-22', out)
            write(d, '.agents/onboarding.md', '<!-- Generated by onboard: -->\n')
            self.assertIn('`.agents/onboarding.md` — generated\n', self.run_facts(d) + '\n')

    def test_report_hand_written(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, '.agents/onboarding.md', '# My own notes\n')
            out = self.run_facts(d)
            self.assertIn('- report: `.agents/onboarding.md` — hand-written', out)

    def test_report_ignored_by_git_is_still_found(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
            write(d, '.gitignore', '.agents/\n')
            write(d, '.agents/onboarding.md', '<!-- Generated by onboard: 2026-10-22 -->\n')
            out = self.run_facts(d)
            self.assertIn('— generated 2026-10-22', out)

    def test_old_codemaps_listed_once_as_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'README.md', '# hi\n')
            write(d, 'docs/CODEMAPS/INDEX.md', '<!-- Generated by codemap: 2026-10-21 -->\n# Index\n')
            write(d, 'docs/CODEMAPS/backend.md', '# My own notes\n')
            write(d, 'docs/adr/0001-x.md', '# adr\n')
            write(d, 'AGENTS.md', 'rules\n')
            out = self.run_facts(d)
            self.assertIn('- `docs/CODEMAPS/` (2 files): old codemap output; ignored', out)
            docs = out.split('## Docs')[1]
            self.assertEqual(docs.count('docs/CODEMAPS'), 1)
            self.assertNotIn('CODEMAPS/INDEX.md', out)
            self.assertIn('`docs/` (1 files):', out)
            self.assertIn('ADR folder: `docs/adr/`', out)
            self.assertIn('`README.md`', out)
            self.assertIn('`AGENTS.md`', out)
            self.assertNotIn('maps yet', out)

    def test_nested_codemaps_count_as_old_output(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'docs/CODEMAPS/INDEX.md', '# Index\n')
            write(d, 'docs/CODEMAPS/backend/api.md', '# Api\n')
            write(d, 'docs/CODEMAPS/diagram.png', 'x\n')
            write(d, 'docs/guide.md', '# g\n')
            docs = self.run_facts(d).split('## Docs')[1]
            self.assertIn('- `docs/CODEMAPS/` (3 files): old codemap output; ignored', docs)
            self.assertIn('`docs/` (1 files):', docs)
            self.assertNotIn('backend/api.md', docs)

    def test_only_old_codemaps_still_prints_line(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'docs/CODEMAPS/INDEX.md', '# Index\n')
            out = self.run_facts(d)
            self.assertIn('(1 files): old codemap output; ignored', out)
            self.assertNotIn('(none found)', out.split('## Docs')[1])

    def test_unknown_extensions_and_tree_depth(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, 'a/b/c/d/deep.zzz', 'x\n')
            write(d, 'noext', 'x\n')
            out = self.run_facts(d)
            self.assertIn('other (.zzz)', out)
            self.assertIn('other (no ext)', out)
            self.assertIn('- a/b/c/ (1)', out)
            self.assertNotIn('a/b/c/d/', out)

    def test_output_is_capped(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(120):
                write(d, f'pkg{i}/package.json', '{"name": "p%d"}' % i)
                write(d, f'pkg{i}/docs/x.md', 'x\n')
            out = self.run_facts(d)
            self.assertLessEqual(len(out.splitlines()), 300)

    def test_cli_prints_markdown_and_rejects_bad_root(self):
        script = ROOT / 'skills/onboard/facts.py'
        with tempfile.TemporaryDirectory() as d:
            write(d, 'x.py', 'x\n')
            ok = subprocess.run(['python3', str(script), d], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0)
            self.assertTrue(ok.stdout.startswith('# Repo facts:'))
            bad = subprocess.run(['python3', str(script), os.path.join(d, 'missing')],
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, '')


if __name__ == '__main__':
    unittest.main()
