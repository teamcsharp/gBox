#!/usr/bin/env bash
# Build clownnemesis from source into a local subdirectory.
# The resulting binary is copied to this directory for the Python probe to use.
set -euo pipefail
cd "$(dirname "$0")"
BUILD_DIR="$(pwd)/clownnemesis-build"
if [ ! -d "$BUILD_DIR/clownnemesis" ]; then
    git clone --recursive --depth 1 https://github.com/Clownacy/clownnemesis.git "$BUILD_DIR/clownnemesis"
fi
cd "$BUILD_DIR/clownnemesis"
mkdir -p build
cd build
cmake ..
make -j"$(nproc)"
cp clownnemesis-tool "$(dirname "$BUILD_DIR")/clownnemesis-tool"
echo "Built: $(dirname "$BUILD_DIR")/clownnemesis-tool"
