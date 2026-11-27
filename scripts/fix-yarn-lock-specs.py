#!/usr/bin/env python3
"""Add exact-version specs that Bun's Yarn export drops from desktop/yarn.lock.

When two packages require the same version once as "X" and once as "=X",
`bun install --yarn` writes a single entry keyed only by one of the specs.
Yarn 1 fills the gap online, but `yarn install --offline --frozen-lockfile`
in the Flatpak build fails with "Couldn't find any versions ... in our cache".
This rewrites the entry keys so every exact dependency spec has a key and
fails on any other missing spec. It is idempotent.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEP_LINE = re.compile(r'^    ("?)(?P<name>@?[^"\s]+)\1 "?(?P<range>[^"]+)"?$')


def unquote(spec: str) -> str:
    return spec[1:-1] if spec.startswith('"') and spec.endswith('"') else spec


def split_spec(spec: str) -> tuple[str, str]:
    at = spec.rindex("@", 1)
    return spec[:at], spec[at + 1 :]


def should_quote(spec: str) -> bool:
    # Mirrors Yarn 1's lockfile key quoting.
    return (
        spec.startswith(("true", "false"))
        or re.search(r'[:\s\\",\[\]]', spec) is not None
        or re.match(r"[0-9]", spec) is not None
        or re.match(r"[a-zA-Z]", spec) is None
    )


def format_key(specs: list[str]) -> str:
    return ", ".join(f'"{s}"' if should_quote(s) else s for s in sorted(specs)) + ":"


def main(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    entries: list[tuple[int, list[str], str | None]] = []
    wanted: set[tuple[str, str]] = set()
    in_deps = False
    for index, line in enumerate(lines):
        text = line.rstrip("\n")
        if text and not text.startswith((" ", "#")) and text.endswith(":"):
            specs = [unquote(s.strip()) for s in text[:-1].split(",")]
            entries.append((index, specs, None))
            in_deps = False
        elif text.startswith("  version ") and entries:
            index0, specs, _ = entries[-1]
            entries[-1] = (index0, specs, unquote(text.split(" ", 3)[3]))
        elif text.startswith("  ") and not text.startswith("    "):
            in_deps = text.strip() in ("dependencies:", "optionalDependencies:")
        elif in_deps and (match := DEP_LINE.match(text)):
            wanted.add((match["name"], match["range"]))

    keyed = {spec for _, specs, _ in entries for spec in specs}
    missing = sorted(f"{n}@{r}" for n, r in wanted if f"{n}@{r}" not in keyed)
    unresolved = []
    changed = False
    for spec in missing:
        name, wanted_range = split_spec(spec)
        exact = wanted_range.removeprefix("=").removeprefix("v")
        targets = [
            pos
            for pos, (_, specs, version) in enumerate(entries)
            if version == exact and any(split_spec(s)[0] == name for s in specs)
        ]
        if len(targets) != 1:
            unresolved.append(spec)
            continue
        index, specs, version = entries[targets[0]]
        specs.append(spec)
        lines[index] = format_key(specs) + "\n"
        changed = True

    if unresolved:
        print("yarn.lock has no entry for: " + ", ".join(unresolved), file=sys.stderr)
        return 1
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
        print(f"added missing yarn.lock specs: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: fix-yarn-lock-specs.py YARN_LOCK", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
