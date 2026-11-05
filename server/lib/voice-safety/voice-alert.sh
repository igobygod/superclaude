#!/bin/bash
# Called by voice-alert@<unit>.service when a unit enters failed state.
. /usr/local/lib/voice-safety/common.sh
tg "🚨 Service $1 just failed on $(hostname). It will auto-restart if configured; the 5-min health check will tell you when it recovers."
