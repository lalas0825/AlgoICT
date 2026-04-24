"""
scripts/audit_config_defaults.py
=================================
Scan the engine for all `getattr(config, KEY, DEFAULT)` and `config.cfg(KEY,
DEFAULT)` call sites and report any KEY that is NOT defined in config.py.

Silent config defaults have bitten us multiple times — this script catches
them at audit time instead of at runtime via the `cfg()` warning.

Run:
    python scripts/audit_config_defaults.py

Exit code 0 when all keys are defined, 1 when drift is found (useful for CI).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ENGINE_ROOT / "config.py"
SELF_PATH = Path(__file__).resolve()


def _extract_config_keys(config_path: Path) -> set[str]:
    """Parse config.py and return every top-level assignment target name."""
    tree = ast.parse(config_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in tree.body:
        # Plain `NAME = value`
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    keys.add(t.id)
        # Annotated `NAME: type = value`
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            keys.add(node.target.id)
    return keys


# Patterns match:
#   getattr(config, "KEY", DEFAULT)
#   getattr(config, 'KEY', DEFAULT)
#   config.cfg("KEY", DEFAULT)
#   config.cfg('KEY', DEFAULT)
PATTERNS = [
    re.compile(r'''getattr\s*\(\s*config\s*,\s*["']([A-Z_][A-Z0-9_]*)["']\s*,\s*([^)]+)\)'''),
    re.compile(r'''config\.cfg\s*\(\s*["']([A-Z_][A-Z0-9_]*)["']\s*,\s*([^)]+)\)'''),
]

# Files/directories to skip (tests use fixtures that can reference non-existent keys)
SKIP_DIRS = {"tests", ".venv", "__pycache__", ".claude", "analysis"}


def _scan_engine(engine_root: Path) -> list[tuple[Path, int, str, str]]:
    """Yield (file, line_no, key, default) tuples for every call site."""
    hits: list[tuple[Path, int, str, str]] = []
    for py_file in engine_root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py_file.parts):
            continue
        if py_file == CONFIG_PATH:
            continue  # skip config.py itself
        if py_file == SELF_PATH:
            continue  # skip this audit script (its docstring / regex patterns trigger false positives)
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in PATTERNS:
                for match in pat.finditer(line):
                    hits.append((py_file, lineno, match.group(1), match.group(2).strip()))
    return hits


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"ERROR: config.py not found at {CONFIG_PATH}", file=sys.stderr)
        return 2

    defined = _extract_config_keys(CONFIG_PATH)
    hits = _scan_engine(ENGINE_ROOT)

    missing: dict[str, list[tuple[Path, int, str]]] = {}
    ok_count = 0
    for file_path, lineno, key, default in hits:
        if key in defined:
            ok_count += 1
        else:
            missing.setdefault(key, []).append((file_path, lineno, default))

    print(f"\nScanned {len(hits)} config accessor call(s).")
    print(f"  OK:      {ok_count} site(s) reference keys defined in config.py")
    print(f"  Missing: {sum(len(v) for v in missing.values())} site(s) "
          f"across {len(missing)} unique key(s)")

    if missing:
        print("\n--- MISSING KEYS (silent defaults in use) ---")
        for key in sorted(missing):
            print(f"\n  {key}:")
            for fp, ln, dft in missing[key]:
                rel = fp.relative_to(ENGINE_ROOT)
                print(f"    {rel}:{ln}  default={dft}")
        print(
            f"\n  Fix: add each key to config.py with the default above (or "
            f"rename the call site to a key that exists)."
        )
        return 1

    print("\nOK: all config accessor keys are defined in config.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
