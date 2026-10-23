#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo 'Run: sudo bash scripts/setup.sh' >&2
  exit 1
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then
  echo 'This installer targets Ubuntu with systemd.' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y software-properties-common
add-apt-repository -y universe
apt-get update
# Do not enable iperf3 as a permanent service; each test starts its own server.
echo 'iperf3 iperf3/start_daemon boolean false' | debconf-set-selections
apt-get install -y mininet openvswitch-switch iperf3 tcpdump iproute2 \
  iputils-ping python3 git
systemctl enable --now openvswitch-switch
modprobe openvswitch
modprobe sch_netem
modprobe sch_tbf
/usr/bin/python3 -c 'import mininet.net; print("Mininet Python import OK")'
ovs-vsctl show
echo 'Setup complete. Run: sudo /usr/bin/python3 topology.py --test'
