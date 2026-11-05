#!/bin/bash
# deploy.sh [agent] [runner] [watcher] - copies from ~/vtest, restarts only what changed, never during a live call
set -e
live=$(sudo python3 - <<'PY'
import json, time
st = {}
for line in open("/var/lib/voicecaller/calls.jsonl"):
    try: e = json.loads(line)
    except Exception: continue
    if e.get("event") in ("dialing", "incoming", "answered", "ended", "not_answered"): st[e["call_id"]] = (e["event"], e["time"])
print(" ".join(c for c, (ev, t) in st.items() if ev in ("dialing", "answered", "incoming") and time.time() - t < 60 * 60))
PY
)
# a call only counts as live if its LiveKit room still exists
rooms=$(cd /srv/voice-caller && sudo bash -c 'set -a; . /etc/voice-caller/livekit.env; venv/bin/python -c "
import asyncio
from livekit import api
async def m():
    async with api.LiveKitAPI() as lk:
        print(\" \".join(r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms))
asyncio.run(m())"' 2>/dev/null || echo UNKNOWN)
if [ "$rooms" != UNKNOWN ]; then live=$(for c in $live; do case " $rooms " in *" $c "*) echo -n "$c ";; esac; done); fi
[ -n "$rooms" ] && [ "$rooms" != UNKNOWN ] && [ -z "$live" ] && live="(unlogged rooms: $rooms)"
running=$(sudo ls /var/lib/voice-tasks/running/ | wc -l)
TS=$(date +%Y%m%d%H%M%S)
for what in "$@"; do
  case $what in
    agent|watcher)
      [ -n "$live" ] && { echo "LIVE CALL ($live): not restarting $what"; continue; }
      f=/srv/voice-caller/$([ $what = agent ] && echo agent.py || echo watcher.py)
      sudo cp $f /root/$(basename $f).bak-$TS; sudo cp ~/vtest/$(basename $f) ~/vtest/test_features.py /srv/voice-caller/
      sudo systemctl restart voice-$([ $what = agent ] && echo caller || echo watcher) ;;
    runner)
      [ -n "$live" ] && { echo "LIVE CALL ($live): not restarting runner (ask line in use)"; continue; }
      [ "$running" != 0 ] && { echo "TASKS RUNNING ($running): not restarting runner"; continue; }
      sudo cp /usr/local/lib/voice-tasks/task_runner.py /root/task_runner.py.bak-$TS
      sudo cp ~/vtest/task_runner.py /usr/local/lib/voice-tasks/task_runner.py; sudo systemctl restart voice-tasks ;;
  esac
  echo "deployed $what"
done
sleep 4; systemctl is-active voice-caller voice-watcher voice-tasks | tr '\n' ' '; echo
