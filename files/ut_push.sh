#!/bin/bash
# Push localhost/goharbor/prepare:dev to 127.0.0.1/library/prepare:dev
# Username: admin, password from $HARBOR_YML (harbor_admin_password)
#
# Usage:
#   ut_push.sh [HARBOR_YML_PATH]
#
# Behavior:
#   1) If the first positional argument is provided it will be used as the
#      path to the harbor.yml file.
#   2) Else if the environment variable HARBOR_YML is set it will be used.
#   3) Otherwise the script falls back to $DATA_VOLUME/harbor.yml as before.
set -e
show_help() {
    cat <<EOF
Usage: $0 [HARBOR_YML_PATH]

Push a prepared image into a local Harbor instance. The harbor admin
password is read from the harbor.yml file.

HARBOR_YML_PATH: optional path to harbor.yml. If omitted the script will
use the HARBOR_YML environment variable if set, otherwise it falls back to
\$DATA_VOLUME/harbor.yml.

Options:
  -h, --help    Show this help message and exit
EOF
}

# Accept -h/--help or first positional argument as harbor yml path
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

if [ -n "$1" ]; then
    HARBOR_YML="$1"
elif [ -n "$HARBOR_YML" ]; then
    : # keep existing env value
else
    HARBOR_YML="./harbor.yml"
fi
if [ ! -f "$HARBOR_YML" ]; then
    echo "WARNING: $HARBOR_YML not found; cannot read harbor_admin_password. Skipping image push."
else
    if ! command -v yq >/dev/null 2>&1; then
        echo "ERROR: yq is required to parse $HARBOR_YML. Please install yq (https://mikefarah.gitbook.io/yq/) and try again."
        exit 1
    fi
    harbor_admin_password=$(yq e '.harbor_admin_password' "$HARBOR_YML")
    if [ -z "$harbor_admin_password" ] || [ "$harbor_admin_password" = "null" ]; then
        echo "WARNING: harbor_admin_password is empty in $HARBOR_YML; skipping image push."
    else
        SRC_IMAGE="quay.io/deamen/alpine-base:latest"
        DST_IMAGE="127.0.0.1/library/alpine-base:latest"

        # Ensure source image exists locally (pull if missing)
        if ! podman images --format '{{.Repository}}:{{.Tag}}' | grep -q "^$SRC_IMAGE$"; then
            echo "Source image $SRC_IMAGE not found locally; pulling it first."
            if ! podman pull "$SRC_IMAGE"; then
                echo "ERROR: failed to pull source image $SRC_IMAGE; cannot proceed with push."
                exit 1
            fi
        fi

        # Try to login and push with retries since Harbor services may take a moment to become ready
        max_retries=12
        delay=5
        pushed=0
        for i in $(seq 1 "$max_retries"); do
            echo "Attempt $i/$max_retries: pushing $SRC_IMAGE -> $DST_IMAGE"
            if podman login 127.0.0.1 -u admin -p "$harbor_admin_password" --tls-verify=false; then
                podman tag "$SRC_IMAGE" "$DST_IMAGE"
                if podman push --tls-verify=false "$DST_IMAGE"; then
                    echo "Image pushed successfully to $DST_IMAGE"
                    pushed=1
                    break
                else
                    echo "podman push failed; will retry after $delay seconds"
                fi
            else
                echo "podman login failed; will retry after $delay seconds"
            fi
            sleep $delay
        done
        if [ "$pushed" -ne 1 ]; then
            echo "ERROR: failed to push $SRC_IMAGE to $DST_IMAGE after $max_retries attempts"
        fi
    fi
fi
