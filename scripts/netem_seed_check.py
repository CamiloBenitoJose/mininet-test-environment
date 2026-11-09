#!/usr/bin/env python3
"""Platform task 1: is netem loss reproducible with a fixed seed?

Builds h1 - s1 - h2 (standalone OVS bridge, no controller), applies netem on
the s1 port that faces h1 (the data direction in the PR2 plan), sends a fixed
ping sequence h2 -> h1, and records exactly which echo requests were dropped.

Trials:
  A, B   loss 5% seed 42            -> should drop the SAME seq numbers
  C      loss 5% seed 43            -> should differ from A
  D, E   loss 5% (no seed)          -> should differ from each other (control)
  GE1/2  Gilbert-Elliott, seed 42   -> should match each other; also reports
                                       mean loss (target 2%) and burst length (target 3)

Run on the Mininet VM:   sudo python3 netem_seed_check.py
Writes netem_seed_check.json next to the script.
"""
import json
import os
import re
import subprocess
import sys

from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.topo import Topo

COUNT = 5000          # pings per trial
INTERVAL = 0.002      # seconds between pings (needs root)
GE = "loss gemodel 0.68% 33.3% 100% 0%"   # p, r, 1-h, 1-k -> 2% mean loss, burst 3

TRIALS = [
    ("A", "loss 5% seed 42"),
    ("B", "loss 5% seed 42"),
    ("C", "loss 5% seed 43"),
    ("D", "loss 5%"),
    ("E", "loss 5%"),
    ("GE1", GE + " seed 42"),
    ("GE2", GE + " seed 42"),
]
PAIRS = [("A", "B", True), ("A", "C", False), ("D", "E", False), ("GE1", "GE2", True)]

SEQ_RE = re.compile(r"icmp_seq=(\d+)")
DROP_RE = re.compile(r"dropped (\d+)")
SEED_RE = re.compile(r"seed (\d+)")


class TwoHost(Topo):
    def build(self):
        h1 = self.addHost("h1")
        h2 = self.addHost("h2")
        s1 = self.addSwitch("s1")
        self.addLink(h1, s1)
        self.addLink(h2, s1)


def sh(*args):
    return subprocess.run(list(args), capture_output=True, text=True)


def silence_stray_traffic(net):
    """Every packet through netem consumes a PRNG draw, so stray IPv6/ARP
    packets would shift the drop pattern. Remove them."""
    for h in net.hosts:
        h.cmd("sysctl -qw net.ipv6.conf.all.disable_ipv6=1 "
              "net.ipv6.conf.default.disable_ipv6=1")
    for intf in net["s1"].intfList():
        if intf.name != "lo":
            sh("sysctl", "-qw", f"net.ipv6.conf.{intf.name}.disable_ipv6=1")
    net.staticArp()


def burst_lengths(lost):
    runs = []
    for s in lost:
        if runs and s == runs[-1][1] + 1:
            runs[-1][1] = s
        else:
            runs.append([s, s])
    return [b - a + 1 for a, b in runs]


def trial(net, port, netem):
    h1, h2 = net["h1"], net["h2"]
    r = sh("tc", "qdisc", "replace", "dev", port, "root", "netem", *netem.split())
    if r.returncode:
        return {"netem": netem, "error": r.stderr.strip()}
    seed_shown = SEED_RE.search(sh("tc", "qdisc", "show", "dev", port).stdout)

    out = h2.cmd(f"ping -n -c {COUNT} -i {INTERVAL} -W 1 {h1.IP()}")
    received = {int(m) for m in SEQ_RE.findall(out)}
    lost = sorted(set(range(1, COUNT + 1)) - received)

    stats = sh("tc", "-s", "qdisc", "show", "dev", port).stdout
    drops = DROP_RE.search(stats)
    sh("tc", "qdisc", "del", "dev", port, "root")

    bl = burst_lengths(lost)
    return {
        "netem": netem,
        "seed_reported_by_tc": seed_shown.group(1) if seed_shown else None,
        "sent": COUNT,
        "lost": len(lost),
        "loss_rate": len(lost) / COUNT,
        "mean_burst_len": (sum(bl) / len(bl)) if bl else 0.0,
        "netem_dropped_counter": int(drops.group(1)) if drops else None,
        "lost_seqs": lost,
    }


def main():
    if os.geteuid() != 0:
        sys.exit("Run with sudo.")
    setLogLevel("warning")

    env = {
        "kernel": sh("uname", "-r").stdout.strip(),
        "tc_version": (sh("tc", "-V").stdout or sh("tc", "-V").stderr).strip(),
    }
    print(f"kernel {env['kernel']} | {env['tc_version']}")

    net = Mininet(topo=TwoHost(), switch=OVSBridge, controller=None,
                  autoSetMacs=True)
    net.start()
    try:
        silence_stray_traffic(net)
        port = net["s1"].connectionsTo(net["h1"])[0][0].name   # s1 port facing h1
        print(f"netem on {port} (s1 -> h1), {COUNT} pings per trial\n")

        results = {}
        for name, netem in TRIALS:
            res = trial(net, port, netem)
            results[name] = res
            if "error" in res:
                print(f"{name:4} {netem:45} TC REJECTED: {res['error']}")
            else:
                print(f"{name:4} {netem:45} loss {res['loss_rate']:6.2%}  "
                      f"burst {res['mean_burst_len']:4.2f}  "
                      f"ping-lost {res['lost']:4}  netem-dropped "
                      f"{res['netem_dropped_counter']}  seed(tc) "
                      f"{res['seed_reported_by_tc']}")
    finally:
        net.stop()

    print("\nPairwise comparison of dropped sequence numbers:")
    verdict_ok = True
    for a, b, expect_same in PAIRS:
        ra, rb = results[a], results[b]
        if "error" in ra or "error" in rb:
            print(f"  {a} vs {b}: skipped (tc error)")
            verdict_ok = False
            continue
        sa, sb = set(ra["lost_seqs"]), set(rb["lost_seqs"])
        same = sa == sb
        jacc = len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
        ok = same == expect_same
        verdict_ok &= ok
        print(f"  {a} vs {b}: identical={same}  overlap(Jaccard)={jacc:.3f}  "
              f"expected identical={expect_same}  -> {'PASS' if ok else 'FAIL'}")

    print("\nVERDICT:", "netem seeding is reproducible on this machine"
          if verdict_ok else "seeding NOT reproducible or not supported - see above")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "netem_seed_check.json")
    with open(out_path, "w") as f:
        json.dump({"env": env, "count": COUNT, "interval_s": INTERVAL,
                   "results": results, "pass": verdict_ok}, f, indent=1)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
