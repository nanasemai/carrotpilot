#!/usr/bin/env bash
if [[ "$(cat ${PARAMS_ROOT:-/data/params}/d/EnableConnect 2>/dev/null || echo "0")" == "2" ]]; then
  export API_HOST="https://api.carrotpilot.app"
  export ATHENA_HOST="wss://athena.carrotpilot.app"
fi
exec ./launch_chffrplus.sh
