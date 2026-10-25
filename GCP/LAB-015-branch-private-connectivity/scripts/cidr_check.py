#!/usr/bin/env python3
"""Reject overlapping IPv4 prefixes before planning or changing Lab 15."""
from __future__ import annotations

import argparse
import ipaddress
import sys


def parse_network(label: str, value: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise ValueError(f"{label} is not a canonical CIDR: {exc}") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError(f"{label} must be IPv4")
    return network


def validate(hub: str, proxy: str, branch: str, additional: str | None) -> list[str]:
    values = [("hub", hub), ("proxy-only", proxy), ("branch", branch)]
    if additional:
        values.append(("branch-additional", additional))
    networks = [(name, parse_network(name, cidr)) for name, cidr in values]
    problems = []
    for index, (name, network) in enumerate(networks):
        for other_name, other in networks[index + 1 :]:
            if network.overlaps(other):
                problems.append(f"CONFLICT: {name} {network} overlaps {other_name} {other}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub", default="10.60.0.0/24")
    parser.add_argument("--proxy", default="10.60.1.0/26")
    parser.add_argument("--branch", default="10.70.0.0/24")
    parser.add_argument("--additional", default="")
    args = parser.parse_args()
    try:
        problems = validate(args.hub, args.proxy, args.branch, args.additional)
    except ValueError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    print("CIDR preflight passed; all supplied IPv4 prefixes are non-overlapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
