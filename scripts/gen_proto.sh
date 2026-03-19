#!/usr/bin/env bash
# Generate Python gRPC stubs from proto files.
# Usage: ./scripts/gen_proto.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$ROOT_DIR/protos"
OUT_DIR="$ROOT_DIR/backend/hermes/generated"

mkdir -p "$OUT_DIR"

python3 -m grpc_tools.protoc \
    -I"$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --pyi_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_DIR/hermes_bridge.proto"

echo "Proto stubs generated in $OUT_DIR"
