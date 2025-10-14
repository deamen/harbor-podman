#!/usr/bin/env python3
"""Scan container directories for UID flags in Dockerfiles and emit a YAML map."""

import argparse
import os
import shlex
from typing import Dict, Iterable, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect container UID assignments from Dockerfiles."
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="root",
        default=".",
        help="Path that holds container subfolders (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default="container_uids.yml",
        help="Destination YAML file (default: container_uids.yml)",
    )
    return parser.parse_args()


def read_effective_lines(path: str) -> Iterable[str]:
    """Yield Dockerfile lines with line continuations resolved and comments skipped."""
    pending = ""
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            stripped_newline = raw_line.rstrip("\n")
            stripped = stripped_newline.strip()
            if not stripped:
                if pending:
                    yield pending.strip()
                    pending = ""
                continue
            if stripped.startswith("#"):
                continue
            if stripped_newline.endswith("\\"):
                pending += stripped_newline[:-1] + " "
                continue
            pending += stripped_newline
            if pending:
                yield pending.strip()
                pending = ""
    if pending:
        yield pending.strip()


def extract_uid_from_tokens(tokens: Iterable[str]) -> Optional[str]:
    """Return the first numeric UID hinted by -u/--uid tokens."""
    token_list = list(tokens)
    for index, token in enumerate(token_list):
        if token in {"-u", "--uid"}:
            if index + 1 < len(token_list):
                value = token_list[index + 1]
                if value.isdigit():
                    return value
            continue
        if token.startswith("-u") and token != "-u":
            candidate = token[2:]
            if candidate.startswith("="):
                candidate = candidate[1:]
            if candidate.isdigit():
                return candidate
        if token.startswith("--uid="):
            candidate = token.split("=", 1)[1]
            if candidate.isdigit():
                return candidate
    return None


def find_uid_in_file(path: str) -> Optional[str]:
    for line in read_effective_lines(path):
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            tokens = line.split()
        uid = extract_uid_from_tokens(tokens)
        if uid is not None:
            return uid
    return None


def find_container_uids(root: str) -> Dict[str, Optional[str]]:
    containers: Dict[str, Optional[str]] = {}
    for entry in sorted(os.scandir(root), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        dockerfiles = [
            os.path.join(entry.path, candidate)
            for candidate in ("Dockerfile", "Dockerfile.base")
            if os.path.isfile(os.path.join(entry.path, candidate))
        ]
        if not dockerfiles:
            continue
        uid: Optional[str] = None
        # Prefer the main Dockerfile before the base variant when both exist.
        for dockerfile in sorted(
            dockerfiles, key=lambda path: 0 if path.endswith("Dockerfile") else 1
        ):
            uid = find_uid_in_file(dockerfile)
            if uid is not None:
                break
        containers[entry.name] = uid
    return containers


def write_yaml(mapping: Dict[str, Optional[str]], destination: str) -> None:
    lines = []
    for name, uid in sorted(mapping.items()):
        rendered = "null" if uid is None else uid
        lines.append(f"{name}: {rendered}")
    if not lines:
        lines.append("{}")
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        raise SystemExit(f"Directory not found: {root}")
    mapping = find_container_uids(root)
    # Add extra alias maps required by the deployment
    # - database should mirror db
    # - secret/cert should mirror nginx
    # - secret/core should mirror core
    alias_pairs = {
        "database": "db",
        "secret/cert": "nginx",
        "secret/core": "core",
    }
    for alias, target in alias_pairs.items():
        # Only add alias if not already present; preserve explicit values if present.
        if alias not in mapping:
            mapping[alias] = mapping.get(target)
    output_path = os.path.abspath(args.output)
    write_yaml(mapping, output_path)
    print(f"Wrote {len(mapping)} containers to {output_path}")


if __name__ == "__main__":
    main()
