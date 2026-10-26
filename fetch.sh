#!/usr/bin/env bash
# Downloads the opencode CLI v2 binary into /tmp/oc-build (for the image build).
# Usage: ./fetch.sh <version>. If the version is already downloaded — skips it.
set -euo pipefail

VERSION="${1:?give a version, e.g. ./fetch.sh 2.1.4}"
BUILD=/tmp/oc-build
mkdir -p "$BUILD"

if [ -x "$BUILD/opencode" ] && [ "$(cat "$BUILD/.version" 2>/dev/null)" = "$VERSION" ]; then
  echo ">> $VERSION is already downloaded to $BUILD/opencode — skipping"
  exit 0
fi

URL="https://registry.npmjs.org/@opencode/cli-linux-x64/-/cli-linux-x64-${VERSION}.tgz"
echo ">> downloading ${URL}"
curl -fL --progress-bar -o "$BUILD/cli.tgz" "$URL"
tar -xzf "$BUILD/cli.tgz" -C "$BUILD"
mv "$BUILD/package/bin/opencode" "$BUILD/opencode"
chmod +x "$BUILD/opencode"
echo "$VERSION" > "$BUILD/.version"
echo ">> binary: $BUILD/opencode"
