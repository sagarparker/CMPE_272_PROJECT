"""Fail on detected secrets and vulnerabilities listed in CISA KEV. No severity proxy."""
import argparse
import json
import sys
from pathlib import Path


def evaluate(report, catalog):
    if not isinstance(report.get("Results"), list):
        raise ValueError("Scanner report has no Results array")
    entries = catalog.get("vulnerabilities")
    if not isinstance(entries, list) or not entries:
        raise ValueError("CISA KEV catalog is empty or invalid")
    kev = {entry["cveID"] for entry in entries}
    blocked = []
    secrets = []
    for result in report["Results"]:
        for finding in result.get("Vulnerabilities") or []:
            aliases = {finding.get("VulnerabilityID", ""), *(finding.get("VendorIDs") or [])}
            hits = sorted(aliases & kev)
            if hits:
                blocked.append({"target": result.get("Target"), "package": finding.get("PkgName"),
                                "installed": finding.get("InstalledVersion"), "cves": hits})
        for finding in result.get("Secrets") or []:
            secrets.append({"target": result.get("Target"), "rule": finding.get("RuleID"),
                            "line": finding.get("StartLine")})
        # Strip matched source and context before reports can become CI artifacts.
        if result.get("Secrets"):
            result["Secrets"] = [{key: value for key, value in finding.items()
                                  if key in {"RuleID", "Title", "StartLine", "EndLine", "Severity"}}
                                 for finding in result["Secrets"]]
    return blocked, secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("catalog", type=Path)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text())
        catalog = json.loads(args.catalog.read_text())
        present = {result.get("Type") for result in report.get("Results", []) if result.get("Packages")}
        if not {"npm", "uv", "jar"}.issubset(present):
            raise ValueError("Missing npm, uv, or Java dependency inventory")
        blocked, secrets = evaluate(report, catalog)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"knownExploited": blocked, "secretLocations": secrets}, indent=2))
        return 1 if blocked or secrets else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Security gate could not establish a safe result: " + type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
