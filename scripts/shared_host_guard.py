#!/usr/bin/env python3
"""Shared-host deployment guard. Only stops the explicitly configured project.

Capture --baseline before deployment, then --watch with --armed. Existing
containers and proxy configuration are never changed by this script.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PROJECT = os.environ.get("SHARED_HOST_PROJECT", "").strip()
DOMAINS = tuple(d.strip() for d in os.environ.get("SHARED_HOST_DOMAINS", "").split(",") if d.strip())


def command(args):
    return subprocess.check_output(args, text=True, timeout=20).strip()


def websites():
    result = {}
    for domain in DOMAINS:
        try:
            out = command(["curl", "-s", "-o", "/dev/null", "--max-time", "5",
                           "--resolve", f"{domain}:443:127.0.0.1", "-w", "%{http_code} %{time_total}",
                           f"https://{domain}/"])
            code, elapsed = out.split()
            result[domain] = {"code": int(code), "seconds": float(elapsed)}
        except (subprocess.SubprocessError, ValueError):
            result[domain] = {"code": 0, "seconds": 5.0}
    return result


def snapshot():
    mem = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    ids = command(["docker", "ps", "-q"]).split()
    rows = json.loads(command(["docker", "inspect", *ids])) if ids else []
    old = {r["Id"]: {"name": r["Name"], "restarts": r["RestartCount"], "oom": r["State"]["OOMKilled"]}
           for r in rows if (r["Config"].get("Labels") or {}).get("com.docker.compose.project") != PROJECT}
    return {"time": time.time(), "available_mib": int(mem["MemAvailable"].split()[0]) // 1024,
            "disk_free_gib": shutil.disk_usage("/").free / (1024 ** 3),
            "websites": websites(), "existing_containers": old}


def issues(before, now):
    failures = []
    if now["available_mib"] < 1536:
        failures.append("available memory below 1536 MiB")
    if now["disk_free_gib"] < 20:
        failures.append("free disk below 20 GiB")
    for domain, old in before["websites"].items():
        current = now["websites"][domain]
        if current["code"] != old["code"] or current["seconds"] > max(1.0, old["seconds"] * 5):
            failures.append("existing website degraded: " + domain)
    for ident, old in before["existing_containers"].items():
        current = now["existing_containers"].get(ident)
        if current is None or current["restarts"] > old["restarts"] or current["oom"] != old["oom"]:
            failures.append("existing container changed: " + old["name"])
    return failures


def stop_project():
    ids = command(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"]).split()
    if ids:
        subprocess.run(["docker", "stop", "--time", "15", *ids], check=True, timeout=120)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--armed", action="store_true")
    parser.add_argument("--duration", type=int, default=86400)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", PROJECT):
        parser.error("Set SHARED_HOST_PROJECT to the exact Compose project name")
    if not DOMAINS or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", d) for d in DOMAINS):
        parser.error("Set SHARED_HOST_DOMAINS to comma-separated DNS hostnames")
    if not args.watch:
        baseline = snapshot()
        if any(v["code"] != 200 for v in baseline["websites"].values()):
            raise SystemExit("Baseline rejected: an existing website is not healthy")
        if issues(baseline, baseline):
            raise SystemExit("Baseline rejected: insufficient resources")
        with args.baseline.open("x") as stream:
            json.dump(baseline, stream, indent=2)
        print("Baseline saved; all existing websites returned 200", flush=True)
        return
    baseline = json.loads(args.baseline.read_text())
    deadline, failures = time.monotonic() + args.duration, 0
    while time.monotonic() < deadline:
        try:
            current = snapshot()
            reasons = issues(baseline, current)
        except Exception as exc:
            reasons = ["guard could not read host state: " + type(exc).__name__]
        failures = failures + 1 if reasons else 0
        print(json.dumps({"time": int(time.time()), "failures": failures, "reasons": reasons}), flush=True)
        if failures >= 3:
            if args.armed:
                stop_project()
                args.baseline.with_suffix(".stopped").write_text("\n".join(reasons))
            raise SystemExit("Deployment stopped by guard" if args.armed else "Guard threshold exceeded")
        time.sleep(20)
    print("Observation period completed", flush=True)


if __name__ == "__main__":
    main()
