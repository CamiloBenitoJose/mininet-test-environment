#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mkdir -p results
{
  date -u
  cat /etc/os-release
  uname -r
  python3 --version
  dpkg-query -W mininet openvswitch-switch iperf3 tcpdump iproute2 python3
  tc -V
} | tee results/environment.txt
