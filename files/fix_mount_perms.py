#!/usr/bin/env python3
"""
Adjust ownership of host mounts referenced in a docker-compose file so they match
the default UID used inside the container image.

Usage: python3 scripts/fix_mount_perms.py -c path/to/docker-compose.yml [--dry-run]

For each service with an image this script will:
- run: podman run --rm <image> id -u  -> to get the default UID
- for each bind/file mount on the host, run:
    podman unshare chown -R <uid>:<uid> <hostpath>

Notes / assumptions:
- Compose volumes that are named volumes (no host path) are skipped.
- Relative host paths are resolved relative to the compose file location.
- If a host path does not exist the path will be skipped and a warning printed.
- We chown to uid:uid (owner and group set to the same uid) which is a reasonable
  default when only a uid is known.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except Exception:  # pragma: no cover - fall back helpful message
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise


def load_compose(path: str) -> Dict[str, Any]:
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def iter_service_volumes(service: Dict[str, Any]) -> Iterable[str]:
    """Yield host paths for bind/file mounts from a service 'volumes' entry.

    Supports both short string syntax and long mapping syntax from compose.
    """
    vols = service.get("volumes") or []
    for v in vols:
        if isinstance(v, str):
            # short syntax: host_path:container_path[:mode]
            parts = v.split(":", 2)
            if len(parts) >= 2:
                host = parts[0]
                # if left side is empty or a named volume (no leading /), skip
                if host == "" or host.startswith("/") or host.startswith(".") or host.startswith("~"):
                    yield host
        elif isinstance(v, dict):
            # long syntax.
            # Example: { type: 'bind', source: './certs', target: '/etc/certs' }
            t = v.get("type")
            src = v.get("source") or v.get("src")
            if (t is None or t == "bind") and src:
                yield src


def get_image_uid(image: str) -> Optional[int]:
    """Run podman to get the default UID for the image. Returns None on failure."""
    # Always use --entrypoint id form and qualify short names with docker.io/
    def qualify(img: str) -> str:
        first = img.split('/', 1)[0]
        if '.' in first or ':' in first or first == 'localhost':
            return img
        return f"docker.io/{img}"

    qualified_image = qualify(image)
    cmd = ["podman", "run", "--rm", "--entrypoint", "id", qualified_image, "-u"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("podman not found in PATH", file=sys.stderr)
        return None

    if res.returncode != 0:
        print(f"Failed to run '{' '.join(cmd)}': rc={res.returncode}\n{res.stderr}", file=sys.stderr)
        return None

    out = res.stdout.strip()
    try:
        return int(out)
    except Exception:
        print(f"Unable to parse uid from output: {out}", file=sys.stderr)
        return None


def resolve_host_path(host_path: str, compose_dir: str) -> str:
    host_path = os.path.expanduser(host_path)
    if os.path.isabs(host_path):
        return os.path.abspath(host_path)
    # treat relative paths as relative to the compose file directory
    return os.path.abspath(os.path.join(compose_dir, host_path))


def chown_path(uid: int, path: str, dry_run: bool = False, recursive: bool = True) -> int:
    cmd = ["podman", "unshare", "chown"]
    if recursive:
        cmd.append("-R")
    cmd.extend([f"{uid}:{uid}", path])
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return 0
    print("Running:", " ".join(cmd))
    # capture output for debugging; return the rc
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        print("chown stdout:", res.stdout.strip())
    if res.stderr:
        print("chown stderr:", res.stderr.strip(), file=sys.stderr)
    print("chown rc:", res.returncode)
    return res.returncode


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fix host mount ownership to match container image UID")
    p.add_argument("-c", "--compose", default="docker-compose.yml", help="Path to docker-compose.yml")
    p.add_argument("--dry-run", action="store_true", help="Print actions instead of executing them")
    p.add_argument("--no-recursive", "-n", dest="no_recursive", action="append", default=[],
                   help="Host path (absolute or relative to compose dir) that should use non-recursive chown; repeatable")
    args = p.parse_args(argv)

    compose_path = os.path.abspath(args.compose)
    if not os.path.exists(compose_path):
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 2

    compose_dir = os.path.dirname(compose_path) or os.getcwd()
    data = load_compose(compose_path)
    services = data.get("services") or {}

    if not services:
        print("No services found in compose file.")
        return 0

    overall_rc = 0
    for name, svc in services.items():
        image = svc.get("image")
        if not image:
            print(f"Service '{name}' has no image; skipping")
            continue
        print(f"Service: {name}  image: {image}")
        uid = get_image_uid(image)
        if uid is None:
            print(f"Unable to determine UID for image {image}; skipping service {name}", file=sys.stderr)
            overall_rc = max(overall_rc, 3)
            continue
        print(f"Image {image} default UID: {uid}")

        for host_src in iter_service_volumes(svc):
            if not host_src:
                continue
            resolved = resolve_host_path(host_src, compose_dir)
            if not os.path.exists(resolved):
                print(f"Host path does not exist: {resolved}, skipping")
                overall_rc = max(overall_rc, 4)
                continue

            # determine whether this path should be chowned non-recursively
            # normalize the no_recursive paths against compose_dir
            normalized_no_recursive = [resolve_host_path(p, compose_dir) for p in args.no_recursive]
            recursive = True
            for nr in normalized_no_recursive:
                # if the resolved path equals the no-recursive path, or is a child of it,
                # prefer non-recursive only when exactly equal (user asked specific path)
                if os.path.abspath(resolved) == os.path.abspath(nr):
                    recursive = False
                    break

            rc = chown_path(uid, resolved, dry_run=args.dry_run, recursive=recursive)
            overall_rc = max(overall_rc, rc)

    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
