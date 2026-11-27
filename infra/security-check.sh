#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p security-reports
# Inspect the resolved runtime JAR rather than resolving its POM a second time.
test -f backend/target/media-backend-0.1.0-SNAPSHOT.jar || {
  echo "Build backend with mvn verify before scanning" >&2; exit 2;
}
# Fixed official release; no mutable scanner action or latest tag.
SCANNER_IMAGE=aquasec/trivy@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
docker run --rm -v "$PWD:/repo:ro" -v "$PWD/security-reports:/reports" \
  -v mediamesh-trivy-cache:/root/.cache/trivy "$SCANNER_IMAGE" fs \
  --scanners vuln,secret --list-all-pkgs --include-dev-deps --ignorefile /dev/null --secret-config /repo/infra/security/trivy-secret.yaml --format json --output /reports/trivy.json \
  --timeout 10m --skip-files /repo/backend/pom.xml --skip-dirs /repo/.git --skip-dirs /repo/.idea \
  --skip-dirs /repo/.metals --skip-dirs /repo/.vscode \
  --skip-dirs /repo/frontend/node_modules --skip-dirs /repo/frontend/dist \
  --skip-dirs /repo/frontend/test-results --skip-dirs /repo/ml-service/.venv \
  --skip-dirs /repo/infra/deploy/runtime --skip-dirs /repo/backups \
  --skip-dirs /repo/ml-service/data --skip-dirs /repo/security-reports /repo
# Image scanning inventories nested Spring Boot JARs and runtime OS packages.
docker compose build backend frontend
for component in backend frontend; do
  docker image save "mediamesh-$component:latest" --output "security-reports/$component-image.tar"
  docker run --rm -v "$PWD/security-reports:/reports" \
    -v mediamesh-trivy-cache:/root/.cache/trivy "$SCANNER_IMAGE" image \
    --input "/reports/$component-image.tar" --scanners vuln --list-all-pkgs --ignorefile /dev/null --format json \
    --output "/reports/$component.json" --timeout 10m
  rm "security-reports/$component-image.tar"
done
python3 -c 'import json; from pathlib import Path; p=Path("security-reports/trivy.json"); d=json.loads(p.read_text()); [d["Results"].extend(json.loads(Path("security-reports",name+".json").read_text())["Results"]) for name in ("backend","frontend")]; p.write_text(json.dumps(d))'
curl --fail --silent --show-error --location --connect-timeout 5 --max-time 45 \
  https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json \
  --output security-reports/cisa-kev.json
python3 -m unittest discover -s infra/security -p 'test_*.py'
python3 infra/security/gate.py security-reports/trivy.json security-reports/cisa-kev.json
