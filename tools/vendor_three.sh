#!/usr/bin/env bash
# Vendors three.js (pinned) into web/vendor/three/ — no CDN at runtime.
# Bare 'three' imports in the example modules are rewritten to a relative path (the page CSP forbids inline import maps).
set -euo pipefail
VER=${THREE_VERSION:-0.170.0}
HERE=$(cd "$(dirname "$0")/.." && pwd)
DST="$HERE/web/vendor/three"
TMP=$(mktemp -d)
( cd "$TMP" && npm pack --silent "three@$VER" >/dev/null 2>&1 && tar xzf "three-$VER.tgz" )
P="$TMP/package"
mkdir -p "$DST/addons/loaders" "$DST/addons/controls" "$DST/addons/exporters" "$DST/addons/utils" "$DST/addons/libs"
cp "$P/build/three.module.min.js" "$DST/three.module.min.js"
cp "$P/LICENSE" "$DST/LICENSE"
for f in loaders/GLTFLoader.js loaders/PLYLoader.js loaders/OBJLoader.js loaders/STLLoader.js loaders/USDZLoader.js \
         controls/OrbitControls.js exporters/STLExporter.js utils/BufferGeometryUtils.js libs/fflate.module.js; do
  depth=$(echo "$f" | awk -F/ '{print NF}')   # addons/<dir>/<file> -> ../../three.module.min.js
  sed -e "s#from 'three'#from '../../three.module.min.js'#g" -e 's#from "three"#from "../../three.module.min.js"#g' \
      "$P/examples/jsm/$f" > "$DST/addons/$f"
done
echo "three@$VER" > "$DST/VERSION"
rm -rf "$TMP"
echo "vendored three@$VER into $DST"
