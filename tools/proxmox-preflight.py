"""Проверка ресурсов новой VM; API только GET, секреты не выводятся."""

import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import math
from collections.abc import Mapping, Sequence
from typing import TypedDict
from json_boundary import JSONObject, JSONValue, json_object


class MemoryAdmission(TypedDict):
    assignedBytes: int
    requestedBytes: int
    remainingBytes: int
    reserveBytes: int


class PreflightArguments(argparse.Namespace):
    profile: Path
    vm_id: int
    memory_gib: int
    disk_gib: int
    output: Path


def _bytes(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Invalid Proxmox memory/storage bytes")
    return value


def _number(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError("Invalid Proxmox CPU state")
    return float(value)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid Proxmox configuration string")
    return value


def _rows(value: JSONValue) -> list[JSONObject]:
    if not isinstance(value, list):
        raise ValueError("Expected Proxmox API resource list")
    return [json_object(item) for item in value]


GiB = 1024**3


def admit(
    node: Mapping[str, object],
    guests: Sequence[Mapping[str, object]],
    vm_id: int,
    memory_bytes: int,
    reserve_bytes: int = 4 * GiB,
) -> MemoryAdmission:
    if any(g.get("vmid") == vm_id for g in guests):
        raise ValueError("VMID already exists")
    assigned = sum(
        _bytes(g.get("maxmem", 0))
        for g in guests
        if g.get("status") == "running" and g.get("type") in ("qemu", "lxc")
    )
    remaining = _bytes(node["maxmem"]) - assigned - memory_bytes
    if remaining < reserve_bytes:
        raise ValueError("Insufficient assigned-memory headroom")
    if _number(node.get("cpu", 1)) > 0.85:
        raise ValueError("Host CPU busy; retry admission later")
    return {
        "assignedBytes": assigned,
        "requestedBytes": memory_bytes,
        "remainingBytes": remaining,
        "reserveBytes": reserve_bytes,
    }


def profile_environment(profile: Path) -> dict[str, str]:
    wanted = {"PROXMOX_VE_API_TOKEN", "BOSCO_SSH_KEY"}
    result: dict[str, str] = {}
    for line in (profile / "environment.fish").read_text().splitlines():
        values = shlex.split(line, comments=True)
        if not values or values[0] != "set":
            continue
        for key in wanted:
            if key in values:
                result[key] = values[values.index(key) + 1].replace(
                    "$HOME", str(Path.home())
                )
    if not result.get("PROXMOX_VE_API_TOKEN"):
        raise ValueError("API token missing")
    result["SSL_CERT_FILE"] = str(profile / "tls/proxmox-root-ca.crt")
    return result


def api(endpoint: str, environment: Mapping[str, str], path: str) -> JSONValue:
    header = (
        "header = "
        + json.dumps(
            "Authorization: PVEAPIToken=" + environment["PROXMOX_VE_API_TOKEN"]
        )
        + "\n"
    )
    response = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "5",
            "--max-time",
            "20",
            "--cacert",
            environment["SSL_CERT_FILE"],
            "--config",
            "-",
            endpoint.rstrip("/") + "/api2/json/" + path,
        ],
        input=header,
        text=True,
        capture_output=True,
    )
    if response.returncode:
        raise ValueError("API GET failed: " + path + "; " + response.stderr.strip())
    return json_object(json.loads(response.stdout))["data"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--vm-id", type=int, required=True)
    parser.add_argument("--memory-gib", type=int, default=8)
    parser.add_argument("--disk-gib", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=PreflightArguments())
    settings = json_object(
        json.loads((args.profile / "production.tfvars.json").read_text())
    )
    env = profile_environment(args.profile)
    node_name = _string(settings["node_name"])
    endpoint = _string(settings["proxmox_endpoint"])
    nodes = _rows(api(endpoint, env, "nodes"))
    node = next(n for n in nodes if n["node"] == node_name and n["status"] == "online")
    guests = _rows(api(endpoint, env, "cluster/resources"))
    memory = admit(node, guests, args.vm_id, args.memory_gib * GiB)
    storage = next(
        s
        for s in _rows(api(endpoint, env, "nodes/" + node_name + "/storage"))
        if s["storage"] == settings["system_storage_id"] and s["active"]
    )
    if _bytes(storage["avail"]) < (args.disk_gib + 32) * GiB:
        raise ValueError("Insufficient disk headroom")
    networks = _rows(api(endpoint, env, "nodes/" + node_name + "/network"))
    if not any(
        n["iface"] == settings["network_bridge"] and n.get("active") for n in networks
    ):
        raise ValueError("Bridge unavailable")
    result: dict[str, object] = {
        "time": datetime.datetime.now(datetime.UTC).isoformat(),
        "node": node_name,
        "vmId": args.vm_id,
        "memory": memory,
        "storage": storage["storage"],
        "diskAvailableBytes": storage["avail"],
        "bridge": settings["network_bridge"],
        "existingGuests": [
            {
                "id": g.get("vmid"),
                "name": g.get("name"),
                "status": g.get("status"),
                "maxmem": g.get("maxmem"),
            }
            for g in guests
            if g.get("type") in ("qemu", "lxc")
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", opener=lambda p, f: os.open(p, f, 0o600)) as file:
        json.dump(result, file, indent=2)
    print(
        json.dumps(
            {
                "node": node_name,
                "vmId": args.vm_id,
                "memory": memory,
                "bridge": settings["network_bridge"],
                "admitted": True,
            }
        )
    )


if __name__ == "__main__":
    main()
