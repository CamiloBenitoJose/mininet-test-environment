# Runtime validation — October 22, 2026 (America/New_York)

Completed in the existing Network Project VirtualBox VM. The second run began
at 2026-10-23 03:37:49 UTC. Setup and all four profile commands exited with code 0.

| Check | Observed | Assessment |
| --- | --- | --- |
| Baseline connectivity | 20/20 ping replies, 0.020 ms mean RTT | Pass |
| Delay calibration | 101.545 ms mean RTT, 20/20 replies | Near 100 ms target |
| Bandwidth calibration | 9.559761 Mbps TCP receiver rate over 20 seconds | Consistent with 10 Mbps shaping and protocol overhead |
| Random loss | 4.3% loss across 1,000 pings | Consistent with configured 5% random loss |
| Packet captures | Four valid Ethernet PCAP files; ICMP and TCP in each | Pass |
| Capture size and drops | 10,000 packets per capture, 1.21–1.39 MB, zero kernel drops reported | Pass |

The unrestricted baseline TCP rate was 24,043.679 Mbps. This is traffic between
namespaces inside the same VM, not physical NIC or Internet throughput. Delay
and loss are tested separately from the 10 Mbps bandwidth limit.

## Environment

- Ubuntu 26.04.1 LTS; kernel 7.0.0-38-generic
- VirtualBox VM: 4 CPUs, 16 GB RAM, NAT networking
- Mininet package: 2.3.0-1.1build1
- Open vSwitch package: 3.7.1-2
- iperf3 package: 3.20-2
- tcpdump package: 4.99.6-1
- iproute2 package: 6.19.0-1ubuntu1.1
- Ubuntu python3 package: 3.14.3-0ubuntu2
- The version-report script's PATH-selected `python3` reported 3.14.4;
  the topology runner explicitly used `/usr/bin/python3`.

## Capture fix verified

The first run passed the network commands but captured unrestricted traffic
without a size bound, producing large files and kernel capture drops. The
validated runner uses `tcpdump -s 128 -c 10000 -B 4096`: a bounded header sample.
All four files were parsed record by record, checking headers, lengths, packet
counts, and the presence of ICMP and TCP. The files are intentionally truncated
to 128 bytes per packet and are not complete recordings of the full transfer.

## Scope and limits

These measurements come from the existing VM, where most dependencies were
already installed. The setup script succeeded and installed Git, but a clean
Ubuntu installation was not tested. Code was transferred through a temporary
VirtualBox shared folder and executed on the guest's local filesystem; the
private-repository clone/authentication flow inside Ubuntu was not tested.

Results vary with VM load, kernel, and package versions. Random loss is
independent netem loss, not Gilbert–Elliott burst loss. Raw captures and generated
results remain local and are excluded from GitHub.
