#!/usr/bin/env python3
"""Translate container UIDs into host UIDs using the current user's subuid range."""

import argparse
import os
import pwd
from typing import Dict, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate host UID map based on container UID definitions."
    )
    parser.add_argument(
        "-m",
        "--map",
        dest="map_path",
        default="container_uids.yml",
        help="YAML file with container->container UID mapping (default: container_uids.yml)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default="container_host_uids.yml",
        help="Destination YAML file (default: container_host_uids.yml)",
    )
    parser.add_argument(
        "--subuid-file",
        dest="subuid_file",
        default="/etc/subuid",
        help="Path to the subuid file (default: /etc/subuid)",
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
                continue
            if val.isdigit():
                mapping[key] = int(val)
                continue
            raise ValueError(f"Unsupported value '{val}' for container '{key}'")
    return mapping


def load_container_map(map_path: str) -> Dict[str, Optional[int]]:
    if not os.path.isfile(map_path):
        raise SystemExit(f"UID map file not found: {map_path}")
    with open(map_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    if not content.strip():
        return {}
    if yaml is not None:
        data = yaml.safe_load(content) or {}
        if not isinstance(data, dict):
            raise SystemExit("Container UID map must be a YAML mapping")
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


def get_current_user_subuid(subuid_file: str) -> int:
    username = pwd.getpwuid(os.getuid()).pw_name
    if not os.path.isfile(subuid_file):
        raise SystemExit(f"subuid file not found: {subuid_file}")
    with open(subuid_file, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 3:
                continue
            if parts[0] == username:
                try:
                    return int(parts[1])
                except ValueError as exc:
                    raise SystemExit(f"Invalid subuid base for {username}: {parts[1]}") from exc
    raise SystemExit(f"No subuid entry found for user {username}")


def compute_host_uids(
    mapping: Dict[str, Optional[int]], subuid_base: int
) -> Dict[str, Optional[int]]:
    host_map: Dict[str, Optional[int]] = {}
    for name, container_uid in mapping.items():
        if container_uid is None:
            host_map[name] = None
        else:
            if os.getuid() != 0:
                host_map[name] = subuid_base + container_uid - 1
            else:
                host_map[name] = subuid_base + container_uid
    return host_map


def write_yaml(mapping: Dict[str, Optional[int]], destination: str) -> None:
    lines = []
    for name, uid in sorted(mapping.items()):
        rendered = "null" if uid is None else str(uid)
        lines.append(f"{name}: {rendered}")
    if not lines:
        lines.append("{}")
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    map_path = os.path.abspath(args.map_path)
    container_map = load_container_map(map_path)
    subuid_base = get_current_user_subuid(args.subuid_file)
    host_map = compute_host_uids(container_map, subuid_base)
    output_path = os.path.abspath(args.output)
    write_yaml(host_map, output_path)
    print(f"Wrote {len(host_map)} container host UIDs to {output_path}")


if __name__ == "__main__":
    main()
