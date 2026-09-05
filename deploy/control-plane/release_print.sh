#!/usr/bin/env bash
# Install a reviewed release archive, retaining the complete previous deployment.
set -euo pipefail
archive=${1:?release archive required}
release_id=${2:?release id required}
[[ "$release_id" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
current=/opt/two-to-three
release=/opt/two-to-three-releases/$release_id
backup=/opt/two-to-three-backup-$release_id
test ! -e "$release"
test ! -e "$backup"
mkdir -p "$release"
tar -xzf "$archive" -C "$release"
cp "$current/deploy/control.env" "$release/deploy/control.env"
chmod 600 "$release/deploy/control.env"
python3 -m venv "$release/.venv"
"$release/.venv/bin/pip" install -q -r "$release/requirements.txt"
"$release/.venv/bin/python" -m compileall -q "$release/server"
systemctl stop two-to-three-control
tar -czf "/opt/print-data-backup-$release_id.tar.gz" -C /root/AIData/3d data
mv "$current" "$backup"
ln -s "$release" "$current"
systemctl start two-to-three-control
for attempt in {1..20}; do
  if curl -fsS http://127.0.0.1:8000/api/system/health >/dev/null; then
    echo "RELEASE_OK=$release_id BACKUP=$backup"
    exit 0
  fi
  sleep 1
done
systemctl stop two-to-three-control
unlink "$current"
mv "$backup" "$current"
systemctl start two-to-three-control
echo 'Release health check failed; restored previous deployment' >&2
exit 1
