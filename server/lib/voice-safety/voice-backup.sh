#!/bin/bash
# Nightly backup, keeps 7 days. Root-only (mode 600).
. /usr/local/lib/voice-safety/common.sh
set -u; umask 077
D=/var/backups/voice-agent; mkdir -p $D; chmod 700 $D
H=/home/claude-helper/assistant
need=$(du -sk /var/lib/voicecaller /var/lib/voice-tasks /etc/voice-caller /srv/voice-caller --exclude=/srv/voice-caller/venv --exclude=venv $H/notes $H/jobs 2>/dev/null | awk '{s+=$1}END{print s}')
free=$(df -k --output=avail $D | tail -1)
if [ "$free" -lt $(( need*3 + 1048576 )) ]; then tg "⚠️ Voice backup skipped: not enough free disk (${free}KB free, need ~$((need*3))KB)."; exit 1; fi
EXTRA=$(for d in /var/lib/voice-memory /var/lib/voice-questions /var/lib/voice-usage /var/lib/voice-extras /var/lib/voice-install /var/lib/voice-dashboard /usr/local/lib/voice-memory /usr/local/lib/voice-extras /usr/local/lib/voice-notify /usr/local/lib/voice-dashboard /usr/local/lib/voice-sip-relay /var/log/voice-install.log; do [ -e $d ] && echo $d; done)
tmp=$(mktemp -d); trap 'rm -rf $tmp' EXIT
docker exec voice-caller-redis-1 redis-cli SAVE >/dev/null 2>&1; docker cp voice-caller-redis-1:/data/dump.rdb $tmp/redis-dump.rdb 2>/dev/null
f=$D/voice-agent-$(date +%Y%m%d-%H%M).tar.gz
tar -czf $f --warning=no-file-changed \
  --exclude='/var/lib/voice-tasks/tmp' --exclude='*.wav' --exclude='*.mp3' --exclude='*.mp4' --exclude='/srv/voice-caller/venv' --exclude='__pycache__' \
  /var/lib/voicecaller /var/lib/voice-tasks /etc/voice-caller $EXTRA \
  /srv/voice-caller /etc/systemd/system/voice-*.service /etc/systemd/system/voice-*.d /etc/systemd/system/voice-*.timer /etc/systemd/system/voice-alert@.service \
  /usr/local/lib/voice-tasks /usr/local/lib/voice-safety $H/notes $H/jobs $H/CLAUDE.md /etc/nginx/sites-available/voice \
  -C $tmp redis-dump.rdb 2>/tmp/voice-backup.err
rc=$?
if [ $rc -gt 1 ] || ! tar -tzf $f >/dev/null 2>&1; then tg "⚠️ Voice backup FAILED (tar exit $rc)."; rm -f $f; exit 1; fi
chmod 600 $f
find $D -name 'voice-agent-*.tar.gz' -mtime +6 -delete
echo "ok $f $(du -h $f | cut -f1) kept=$(ls $D | wc -l)"
exit 0
