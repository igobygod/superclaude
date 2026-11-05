#!/bin/bash
# Voice-agent health check (runs every 5 min). One alert per new problem (after 2 consecutive bad runs), one "recovered" when fixed.
. /usr/local/lib/voice-safety/common.sh
STATE=/var/lib/voice-safety/health.json
mkdir -p /var/lib/voice-safety
probs=()
for s in voice-caller voice-watcher voice-tasks; do
  systemctl is-active --quiet $s || probs+=("service:$s")
done
running=$(docker ps --format '{{.Names}}' 2>/dev/null)
for c in voice-caller-redis-1 voice-caller-livekit-1 voice-caller-sip-1; do
  grep -qx "$c" <<<"$running" || probs+=("container:$c")
done
[ -s /var/lib/voicecaller/trunk_id ] || probs+=("sip-trunk-file-missing")
use=$(df --output=pcent / | tail -1 | tr -dc 0-9); [ "${use:-0}" -gt 90 ] && probs+=("disk:${use}%")
avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ "${avail:-9999}" -lt 300 ] && probs+=("memory-low:${avail}MB")
[ -e /var/lib/voice-tasks/STOP ] && : # kill switch is intentional, not a fault
python3 - "$STATE" "${probs[@]}" <<'PY' > /run/voice-health.out
import sys,json,os
st=sys.argv[1]; now=set(sys.argv[2:])
try: old=json.load(open(st))
except Exception: old={"seen":{}, "alerted":[]}
seen={k:old["seen"].get(k,0)+1 for k in now}
alerted=set(old["alerted"])
new=[k for k in now if seen[k]>=2 and k not in alerted]
rec=[k for k in alerted if k not in now]
alerted=(alerted|set(new))-set(rec)
json.dump({"seen":seen,"alerted":sorted(alerted)},open(st,"w"))
print("NEW="+",".join(sorted(new)));print("REC="+",".join(sorted(rec)));print("OPEN="+",".join(sorted(alerted)))
PY
NEW=$(sed -n 's/^NEW=//p' /run/voice-health.out); REC=$(sed -n 's/^REC=//p' /run/voice-health.out); OPEN=$(sed -n 's/^OPEN=//p' /run/voice-health.out)
host=$(hostname)
[ -n "$NEW" ] && tg "⚠️ Voice agent problem on $host: ${NEW//,/, }$( [ -n "$OPEN" ] && echo " (still open: ${OPEN//,/, })")"
if [ -n "$REC" ]; then
  if [ -z "$OPEN" ]; then tg "✅ Voice agent recovered: ${REC//,/, }. Everything is healthy again."
  else tg "✅ Fixed: ${REC//,/, }. Still open: ${OPEN//,/, }"; fi
fi
exit 0
