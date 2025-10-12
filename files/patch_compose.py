#!/usr/bin/env python3
"""Patch a docker-compose.yml for Podman logging settings using values from harbor.yml.

Behavior:
- Accept a docker-compose file and harbor.yml (optional) as inputs.
- Remove the `log` service entirely and remove `log` from any `depends_on` entries.
- For every service, set logging.driver to `json-file`.
- Remove logging.options `syslog-address` and `tag`.
- Add logging.options:
  - path: <harbor.log.local.location>/<original_tag>.log
  - max-size: <harbor.log.local.rotate_size>
  - max-file: <harbor.log.local.rotate_count>

Note: This script uses ruamel.yaml to preserve formatting/comments.
"""

from __future__ import annotations
import argparse
import os
import sys
from typing import Any

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
    from ruamel.yaml.scalarstring import SingleQuotedScalarString
except Exception as exc:
    print(
        "This script requires 'ruamel.yaml'. Install with: pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise


def load_yaml(path: str) -> Any:
    yaml = YAML()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f)


def write_yaml(path: str, data: Any) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def sanitize_rotate_size(size: str) -> str:
    # Accept values like '200M' or '100k' and return them unchanged.
    return str(size)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch docker-compose.yml logging for podman using harbor.yml"
    )
    parser.add_argument(
        "-c",
        "--compose",
        default="docker-compose.yml",
        help="Path to docker-compose.yml to patch",
    )
    parser.add_argument(
        "-y",
        "--harbor",
        default="harbor.yml",
        help="Path to harbor.yml to read log settings from",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Save a backup of the original compose file as .bak",
    )
    args = parser.parse_args()

    compose_path = os.path.abspath(args.compose)
    harbor_path = os.path.abspath(args.harbor)

    if not os.path.exists(compose_path):
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 2
    if not os.path.exists(harbor_path):
        print(f"Harbor file not found: {harbor_path}", file=sys.stderr)
        return 2

    if args.backup:
        bak = compose_path + ".bak"
        with open(compose_path, "rb") as src, open(bak, "wb") as dst:
            dst.write(src.read())
        print(f"Backup written to {bak}")

    harbor = load_yaml(harbor_path) or {}
    log_cfg = (harbor.get("log") or {}).get("local") or {}
    rotate_size = sanitize_rotate_size(log_cfg.get("rotate_size", ""))
    rotate_count = log_cfg.get("rotate_count", "")
    location = log_cfg.get("location", "")

    if not location:
        print(
            "Warning: harbor.yml does not define log.local.location; 'path' option will be set to '/var/log' by default."
        )
        location = "/var/log"
    if not rotate_size:
        print(
            "Warning: harbor.yml does not define log.local.rotate_size; 'max-size' will be left empty."
        )
    if rotate_count in (None, ""):
        print(
            "Warning: harbor.yml does not define log.local.rotate_count; 'max-file' will be left empty."
        )

    compose = load_yaml(compose_path) or {}
    services = compose.get("services") or CommentedMap()

    # Remove the log service if present
    if "log" in services:
        del services["log"]
        print("Removed 'log' service")

    for svc_name, svc in list(services.items()):
        if not isinstance(svc, dict):
            continue

        # Remove depends_on reference to log
        depends = svc.get("depends_on")
        if depends:
            # depends_on can be a list or mapping
            if isinstance(depends, list):
                new_dep = [d for d in depends if d != "log"]
                if new_dep != depends:
                    if new_dep:
                        svc["depends_on"] = new_dep
                    else:
                        del svc["depends_on"]
            elif isinstance(depends, dict):
                if "log" in depends:
                    depends.pop("log", None)
                    if not depends:
                        del svc["depends_on"]

        # Ensure logging exists
        logging = svc.get("logging")
        original_tag = svc_name
        if logging is None:
            logging = CommentedMap()
            svc["logging"] = logging

        # Set driver to json-file
        logging["driver"] = "json-file"

        # Ensure options map exists
        opts = logging.get("options")
        if opts is None:
            opts = CommentedMap()
            logging["options"] = opts

        # Capture original tag if present, then remove tag and syslog-address
        tag_val = None
        if "tag" in opts:
            tag_val = opts.pop("tag")
        if "syslog-address" in opts:
            opts.pop("syslog-address", None)

        if tag_val:
            original_tag = str(tag_val)

        # Build path: <location>/<original_tag>.log
        path_val = os.path.join(location.rstrip("/"), f"{original_tag}.log")
        opts["path"] = path_val

        if rotate_size:
            opts["max-size"] = str(rotate_size)
        if rotate_count not in (None, ""):
            # prefer integer type for max-file when possible (no quotes in output)
            try:
                intval = int(rotate_count)
                opts["max-file"] = intval
            except Exception:
                opts["max-file"] = str(rotate_count)

        # Assign modified logging back
        svc["logging"] = logging

        # Ensure shm_size, if present, is quoted (e.g. '1gb') to preserve units
        if "shm_size" in svc:
            val = svc.get("shm_size")
            if val is not None:
                # Always coerce to a single-quoted scalar string to keep units intact
                svc["shm_size"] = SingleQuotedScalarString(str(val))

    compose["services"] = services
    write_yaml(compose_path, compose)

    print(f"Patched compose file: {compose_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
