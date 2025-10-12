#!/bin/bash
set -euo pipefail

OUT="/data/cert/harbor.crt"
KEYOUT="/data/cert/harbor.key"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -out)
            shift
            OUT="$1"
            ;;
        -keyout)
            shift
            KEYOUT="$1"
            ;;
        *)
            # ignore unknown args
            ;;
    esac
    shift || true
done

if [ -z "${ips:-}" ]; then
        ips=$(hostname -I 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true)
fi
san="subjectAltName=IP:127.0.0.1"
for ip in $ips; do
        # skip empty entries
        [ -z "$ip" ] && continue
        san="$san,IP:$ip"
done

mkdir -p "$(dirname "$OUT")" "$(dirname "$KEYOUT")"

sudo openssl req -newkey rsa:4096 -nodes -x509 -days 30 \
        -subj "/C=AU/ST=Victoria/L=Melbourne/O=deamen/CN=$(hostname)" \
        -addext "$san" \
        -keyout "$KEYOUT" \
        -out "$OUT"

echo "Generated certificate: $OUT and key: $KEYOUT"

