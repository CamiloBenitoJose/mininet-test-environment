# Mininet VM test environment

Recreate a small Linux network for baseline connectivity, approximately 100 ms
round-trip delay, 10 Mbps bandwidth, independent random 5% loss, and packet capture.
The repository contains environment code and instructions, not a VM image.

```text
h1 (10.0.0.1/24) --- s1 (Open vSwitch) --- h2 (10.0.0.2/24)
```

The switch uses standalone learning mode; no external controller is required.
These hosts are Linux network namespaces inside one Ubuntu VM. Their emulated
network does not require bridged networking or connectivity to the Internet.

## Recreate on a teammate's computer

1. Create an Ubuntu VM in VirtualBox (Ubuntu 26.04.1 LTS is the version tested
   in the existing project VM; other releases require validation). A practical starting allocation is
   2 CPUs, 4 GB RAM, and 25 GB disk. NAT networking provides package downloads.
   The original host-side VM configuration has 4 CPUs and 16 GB RAM; matching
   that allocation is optional for this two-host topology.
2. Install Ubuntu, sign in, and open a terminal **inside Ubuntu**. Run:

   ```bash
   sudo apt-get update
   sudo apt-get install -y git
   git clone https://github.com/CamiloBenitoJose/mininet-test-environment.git
   cd mininet-test-environment
   sudo bash scripts/setup.sh
   bash scripts/versions.sh
   sudo /usr/bin/python3 topology.py --test
   ```

   This repository is private. Before cloning,
   accept your collaborator invitation and authenticate using GitHub's supported
   HTTPS or SSH flow. Do not put credentials into the clone URL or tracked files.
3. Run all four independent measurement profiles:

   ```bash
   sudo bash scripts/run-all.sh
   ```

Each profile starts a fresh topology and stops it on completion. Allow several
minutes for the suite. Run only one Mininet session at a time. Setup uses Ubuntu
packages rather than a Python virtual environment; use `/usr/bin/python3` so
Ubuntu's Mininet module is found. Package versions are not pinned: save the
version report with any experiment you need to compare across machines.

## Calibration profiles and interpretation

| Profile | Applied configuration | Expected observation |
| --- | --- | --- |
| `baseline` | No added shaping | Ping succeeds; record local RTT and throughput |
| `delay` | 50 ms netem delay on each host's egress | Ping RTT near baseline + 100 ms |
| `bandwidth` | 10 mbit TBF on each host's egress | Sustained TCP receiver rate near, usually below, 10 Mbps |
| `loss` | 5% random netem loss on h1 egress only | Roughly 5% ping loss over 1,000 requests |

Run an individual profile:

```bash
sudo /usr/bin/python3 topology.py --profile delay --test
sudo /usr/bin/python3 topology.py --profile bandwidth --test
sudo /usr/bin/python3 topology.py --profile loss --test
```

Each run stores `ping.txt`, `iperf.json`, `traffic.pcap`, tcpdump/server logs,
and both host qdisc statistics in `results/<UTC timestamp>-<profile>/`.
The bandwidth measurement uses a 20-second TCP iperf3 transfer; inspect
`end.sum_received.bits_per_second / 1000000` in the JSON for receiver Mbps.
For example, inside Ubuntu:

```bash
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["end"]["sum_received"]["bits_per_second"]/1e6, "Mbps")' results/RUN/iperf.json
```

Replace `RUN` with the actual directory. These are measurements, not automatic
acceptance tests: the runner checks command success and initial connectivity,
but does not claim the measured RTT, bandwidth, or loss met a hard threshold.
The full suite collects TCP performance under every profile, so the loss
profile's TCP rate can be substantially lower than baseline.

Delay is applied only once in each direction: 50 ms request + 50 ms reply.
Adding 50 ms to every port on both links would instead add about 200 ms RTT.
For an unloaded VM, baseline + 100 ms within several milliseconds is a useful
initial target; scheduling load can increase it. Adjust each host's delay by
half the desired RTT correction if necessary, and record the actual settings.

Loss is deliberately one-directional. Applying 5% independently in both
directions produces about 9.75% ping failure, not 5%. With 1,000 requests,
approximately 3.6–6.4% observed loss is a rough 95% sampling interval under
independent drops; values outside it can still occur. This profile is **not**
the Gilbert–Elliott burst-loss model, which remains a future extension.

TBF limits the emulated path, not the VM's NAT adapter. TCP/application payload
rate differs from the configured link rate because of protocol overhead,
startup, and scheduling. Repeat measurements before drawing conclusions.

## Interactive commands

Start a fresh baseline session:

```bash
sudo /usr/bin/python3 topology.py
```

At the `mininet>` prompt:

```text
nodes
net
pingall
h1 ping -c 20 10.0.0.2
```

To configure about 100 ms additional RTT manually:

```text
h1 tc qdisc replace dev h1-eth0 root netem delay 50ms
h2 tc qdisc replace dev h2-eth0 root netem delay 50ms
h1 ping -c 20 10.0.0.2
h1 tc -s qdisc show dev h1-eth0
h2 tc -s qdisc show dev h2-eth0
```

Exit and start a fresh session between experiments so previous settings do
not combine. For bandwidth, start `topology.py --profile bandwidth` and run:

```text
h2 iperf3 -s -1 > /tmp/mininet-iperf-server.log 2>&1 &
h1 iperf3 -c 10.0.0.2 -t 20
```

The one-shot server exits after that transfer. For loss, start
`topology.py --profile loss`, then run:

```text
h1 ping -n -c 1000 -i 0.02 -W 2 10.0.0.2
```

For packet capture, prefer `--test`, which starts tcpdump on `h2-eth0` before
traffic and flushes/stops it afterward. Read a saved capture inside Ubuntu:

```bash
sudo tcpdump -nn -r results/RUN/traffic.pcap -c 20
```

Captures include ICMP and iperf3 port 5201 traffic only, limited to the first
10,000 matching packets and 128 bytes per packet (roughly 1.4 MB maximum).
This is a header sample, not a complete recording of the transfer; tcpdump
can also drop packets under load. Check `tcpdump.log` for capture statistics.
The receiving h2 capture
does not show packets dropped at h1 egress; use ping/iperf and qdisc counters to
interpret loss. To copy root-owned results conveniently:

```bash
sudo chown -R "$(id -u):$(id -g)" results
```

## Troubleshooting

- After an interrupted/crashed session, first ensure no other Mininet experiment
  is running, then run `sudo mn -c`. This removes leftover Mininet resources
  globally; do not use it during another experiment.
- If the switch fails: `sudo systemctl restart openvswitch-switch`, then
  `sudo ovs-vsctl show`.
- If `tc` reports an unknown qdisc: `sudo modprobe sch_netem` and
  `sudo modprobe sch_tbf`. Use a normal Ubuntu kernel with these modules.
- Run from Ubuntu's local home directory if a VirtualBox shared folder has
  permission problems. Execute shell files with `bash` as shown above.
- Windows PowerShell cannot run this topology. Windows is the VM host;
  Mininet, OVS, and traffic control execute in the Linux guest.

## Provenance and validation status

Setup and all four profiles passed in the existing VM. See the
[runtime validation report](docs/validation-2026-10-22.md) for measured results,
versions, the capture fix, and validation limits. A clean VM installation and
GitHub authentication inside Ubuntu have not been tested.

On 2026-10-22, the local VirtualBox configuration for `Network Project` showed
an Ubuntu 64-bit guest, 4 CPUs, 16 GB RAM, and NAT. Subsequent runtime testing
identified Ubuntu 26.04.1 LTS, Mininet 2.3.0, and Open vSwitch 3.7.1.
No pre-existing guest scripts or original experiment results,
or raw VM configuration were imported. This repository reconstructs the
requested environment; it is not a verified export of the guest filesystem.

Run the suite in the existing VM and a fresh teammate VM before treating this
as a validated reproduction. Retain `scripts/versions.sh` output and measured
results with your project records. Do not invent calibration results.

## Team access and contributions

The repository is private:
[CamiloBenitoJose/mininet-test-environment](https://github.com/CamiloBenitoJose/mininet-test-environment).

The owner can invite teammates in
[Settings → Collaborators](https://github.com/CamiloBenitoJose/mininet-test-environment/settings/access).
Each teammate must accept the invitation before cloning or viewing the files.

Clone the published repository using the instructions above, then create a branch
for changes:

```bash
git switch -c my-environment-change
# Edit the relevant files, then inspect and commit only those files.
git status
git add README.md topology.py scripts
git diff --cached --stat
git commit -m "Describe your environment change"
git push -u origin my-environment-change
```

Open a pull request on GitHub for team review. If Git asks for your identity,
configure your own name and verified GitHub email locally with
`git config user.name "Your Name"` and `git config user.email "YOUR_EMAIL"`.

VM disks, installation media, PCAP files, credentials, and generated results
are excluded by `.gitignore`. Review staged files before pushing. No license
is assumed or granted by this repository.

## References

- [Mininet walkthrough](https://mininet.org/walkthrough/)
- [Linux netem manual: delay and loss](https://www.man7.org/linux/man-pages/man8/netem.8.html)
- [iperf3 documentation](https://software.es.net/iperf/invoking.html)
