#!/usr/bin/env python3
"""Recursively assign ACLs to container directories based on a host UID map."""

import argparse
import os
import shlex
import subprocess
from typing import Dict, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply host UID map to container directories."
    )
    parser.add_argument(
        "-m",
        "--map",
        dest="map_path",
        default="container_host_uids.yml",
        help="YAML file with container->host UID mapping (default: container_host_uids.yml)",
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="root",
        default=".",
        help="Directory that holds container subfolders (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned ownership changes without applying them",
    )
    return parser.parse_args()


def load_yaml_simple(map_path: str) -> Dict[str, Optional[int]]:
    mapping: Dict[str, Optional[int]] = {}
    with open(map_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line in {"{}", "[]"}:
                return {}
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.strip()
            val = value.strip().strip('"')
            if not val or val in {"null", "~"}:
                mapping[key] = None
            elif val.isdigit():
                mapping[key] = int(val)
            else:
                raise ValueError(f"Unsupported UID value '{val}' for container '{key}'")
    return mapping


def load_host_map(map_path: str) -> Dict[str, Optional[int]]:
    if not os.path.isfile(map_path):
        raise SystemExit(f"Host UID map file not found: {map_path}")
    with open(map_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    if not content.strip():
        return {}
    if yaml is not None:
        data = yaml.safe_load(content) or {}
        if not isinstance(data, dict):
            raise SystemExit("Host UID map must be a YAML mapping")
        result: Dict[str, Optional[int]] = {}
        for key, value in data.items():
            if value is None:
                result[str(key)] = None
            elif isinstance(value, int):
                result[str(key)] = value
            elif isinstance(value, str) and value.isdigit():
                result[str(key)] = int(value)
            else:
                raise SystemExit(f"Unsupported UID value for container '{key}': {value}")
        return result
    return load_yaml_simple(map_path)


def apply_setfacl(root: str, uid: int, dry_run: bool) -> None:
    command = [
        "setfacl",
        "-R",
        "-m",
        f"u:{uid}:rwx",
        "-m",
        f"g:{uid}:rwx",
        root,
    ]
    if dry_run:
        print("DRY-RUN", shlex.join(command))
        return
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SystemExit("setfacl command not found") from exc
    if result.returncode != 0:
        raise SystemExit(
            "setfacl failed for {}: {}".format(
                root,
                result.stderr.strip() or f"exit code {result.returncode}",
            )
        )


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        raise SystemExit(f"Directory not found: {root}")
    host_map = load_host_map(os.path.abspath(args.map_path))
    processed = 0
    for name, uid in sorted(host_map.items()):
        if uid is None:
            print(f"Skipping {name}: no host UID defined")
            continue
        target = os.path.join(root, name)
        if not os.path.isdir(target):
            print(f"Skipping {name}: directory not found at {target}")
            continue
        apply_setfacl(target, uid, args.dry_run)
        processed += 1
    print(f"Processed {processed} container directories with setfacl")


if __name__ == "__main__":
    main()
