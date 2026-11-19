#!/bin/bash
# Cron wrapper: rootless Podman needs the user's runtime directory, which cron does not set.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
cd "$(dirname "$0")" && exec python3 -I run.py >> cron.log 2>&1
