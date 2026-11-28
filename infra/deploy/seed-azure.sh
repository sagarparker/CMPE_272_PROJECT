#!/bin/sh
# Add demo-manifest media that the Azure catalog does not have yet; see seed_azure.py.
# Run on the VM from /opt/mediamesh:  sudo ./infra/deploy/seed-azure.sh
set -eu
cd "$(dirname "$0")/../.."
STATE=infra/deploy/runtime/demo-upload-state.json
[ -f "$STATE" ] || printf '{"origin":"","assets":{}}\n' > "$STATE"
cp "$STATE" "$STATE.bak-$(date -u +%Y%m%dT%H%M%SZ)"
./infra/deploy/compose.sh cp infra/deploy/seed_azure.py ml-worker:/tmp/seed_azure.py
# Optional verified local copies (e.g. ml-service/data/demo from a checksum-checked download).
if [ -d "${SEED_CACHE:-}" ]; then
  ./infra/deploy/compose.sh exec -T ml-worker mkdir -p /tmp/demo-cache
  ./infra/deploy/compose.sh cp "$SEED_CACHE/." ml-worker:/tmp/demo-cache/
fi
python3 - "$STATE" <<'PY'
import json, os, subprocess, sys
state_path = sys.argv[1]
state = json.load(open(state_path))
manifest = json.load(open("ml-service/evaluation/demo-manifest.json"))
proc = subprocess.Popen(
    ["./infra/deploy/compose.sh", "exec", "-T", "ml-worker", "python", "-u", "/tmp/seed_azure.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
proc.stdin.write(json.dumps({"manifest": manifest, "state": state})); proc.stdin.close()
errors = 0
for line in proc.stdout:
    print(line, end="", flush=True)
    try: event = json.loads(line)
    except ValueError: continue
    if event.get("event") in {"added", "found"}:
        state["assets"][event["id"]] = {k: event[k] for k in ("assetId", "ownerId", "sha256")}
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f: json.dump(state, f, indent=2); f.write("\n")
        os.chmod(tmp, 0o600); os.replace(tmp, state_path)
    errors += event.get("event") == "error"
sys.exit(proc.wait() or (1 if errors else 0))
PY
