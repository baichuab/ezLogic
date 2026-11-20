#!/bin/sh
set -e
if [ ! -f /data/workspace/lakefile.toml ]; then
  cp -a /opt/lean-project/. /data/workspace/
fi
exec "$@"
