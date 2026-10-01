#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m airkeys
status=$?
if [ "$status" -ne 0 ]; then
  echo
  echo "AirKeys stopped with an error."
  read -r -p "Press return to close."
fi
exit "$status"
