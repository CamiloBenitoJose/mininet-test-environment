#!/usr/bin/env python3
"""h1 - s1 - h2 with impairments on the switch ports (PR1 Section 4.4 layout).

The data direction is s1 -> h1. The s1 port facing h1 carries the full tree:
    root netem (RTT/2 delay, loss, seed)  ->  child tbf (rate, burst, buffer)
The s1 port facing h2 carries only the other RTT/2 of delay.
Hosts carry no qdiscs.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import os
import signal
import subprocess
import time

try:
    from mininet.topo import Topo
except ImportError:  # lets plan() be tested on a machine without Mininet
    Topo = object

NETEM_LIMIT = 3000          # packets held by netem (delay line)
MIN_BURST_BYTES = 2 * 1514  # tbf bucket must hold at least two full frames
MIN_BUFFER_BYTES = 64 * 1024  # used when RTT is 0, so the BDP is ~0

PROFILES = {
    'baseline':  {},
    'delay':     {'rtt_ms': 100},
    'bandwidth': {'bw_mbit': 10},
    'loss':      {'loss_pct': 5, 'loss_model': 'random'},
    'geloss':    {'loss_pct': 2, 'loss_model': 'ge'},
}
DEFAULTS = {'rtt_ms': 0, 'bw_mbit': None, 'loss_pct': 0, 'loss_model': 'random',
            'burst_len': 3, 'buffer_bdp': 1.0, 'seed': 42}


class TwoHostTopo(Topo):
    def build(self):
        switch = self.addSwitch('s1', failMode='standalone')
        for number in (1, 2):
            host = self.addHost(f'h{number}', ip=f'10.0.0.{number}/24')
            self.addLink(host, switch)


topos = {'twohost': TwoHostTopo}


def ge_params(loss_pct, burst_len):
    """Gilbert model: bad state always drops, good state never drops.
    Mean burst = 1/r, mean loss L = p / (p + r)  ->  p = L*r / (1 - L)."""
    loss = loss_pct / 100
    r = 1 / burst_len
    p = loss * r / (1 - loss)
    return p * 100, r * 100


def plan(cfg, data_port, reverse_port):
    """Return (tc commands, derived values). Pure function, testable offline."""
    half = cfg['rtt_ms'] / 2
    derived = {'data_port': data_port, 'reverse_port': reverse_port}
    if not (half or cfg['bw_mbit'] or cfg['loss_pct']):
        return [], derived

    netem = ['netem', 'limit', str(NETEM_LIMIT)]
    if half:
        netem += ['delay', f'{half:g}ms']
    if cfg['loss_pct']:
        if cfg['loss_model'] == 'ge':
            p, r = ge_params(cfg['loss_pct'], cfg['burst_len'])
            derived.update(ge_p_pct=p, ge_r_pct=r)
            netem += ['loss', 'gemodel', f'{p:.4f}%', f'{r:.4f}%', '100%', '0%']
        else:
            netem += ['loss', 'random', f"{cfg['loss_pct']:g}%"]
    netem += ['seed', str(cfg['seed'])]
    cmds = [['tc', 'qdisc', 'replace', 'dev', data_port, 'root', 'handle', '1:', *netem]]

    if cfg['bw_mbit']:
        rate_bytes = cfg['bw_mbit'] * 1e6 / 8
        burst = max(math.ceil(rate_bytes / 250), MIN_BURST_BYTES)
        bdp = rate_bytes * cfg['rtt_ms'] / 1000
        limit = max(math.ceil(cfg['buffer_bdp'] * bdp), MIN_BUFFER_BYTES)
        derived.update(bdp_bytes=bdp, tbf_burst_bytes=burst, tbf_limit_bytes=limit)
        cmds.append(['tc', 'qdisc', 'add', 'dev', data_port, 'parent', '1:1',
                     'handle', '10:', 'tbf', 'rate', f"{cfg['bw_mbit']:g}mbit",
                     'burst', str(burst), 'limit', str(limit)])
    if half:
        cmds.append(['tc', 'qdisc', 'replace', 'dev', reverse_port, 'root',
                     'handle', '1:', 'netem', 'limit', str(NETEM_LIMIT),
                     'delay', f'{half:g}ms'])
    return cmds, derived


def checked(node, *args):
    out, err, code = node.pexec(list(args))
    if code:
        raise RuntimeError(f'{node.name}: {args}: {out}{err}')
    return out


def s1_ports(net):
    s1, h1, h2 = net.get('s1', 'h1', 'h2')
    return s1.connectionsTo(h1)[0][0].name, s1.connectionsTo(h2)[0][0].name


def configure(net, cfg):
    s1 = net.get('s1')
    data_port, reverse_port = s1_ports(net)
    cmds, derived = plan(cfg, data_port, reverse_port)
    for cmd in cmds:
        checked(s1, *cmd)
    derived['tc_commands'] = [' '.join(c) for c in cmds]
    for line in derived['tc_commands']:
        print(line)
    return derived


def stop_process(process):
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def measure(net, cfg, folder):
    h1, h2, s1 = net.get('h1', 'h2', 's1')
    # ARP and switch learning were warmed up before applying impairments.
    capture = server = None
    with (folder / 'tcpdump.log').open('w') as caplog, \
            (folder / 'iperf-server.log').open('w') as serverlog:
        try:
            # Capture point moves to h1 in task 5.
            capture = h2.popen(['tcpdump', '-i', 'h2-eth0', '-U', '-n',
                                '-s', '128', '-c', '10000', '-B', '4096',
                                '-w', str(folder / 'traffic.pcap'),
                                'icmp or tcp port 5201 or udp port 5201'],
                               stdout=caplog, stderr=caplog)
            time.sleep(1)
            if capture.poll() is not None:
                raise RuntimeError('tcpdump failed; see tcpdump.log')
            # Echo replies travel s1 -> h1, so ping loss measures the data direction.
            count = '1000' if cfg['loss_pct'] else '20'
            output = checked(h1, 'ping', '-n', '-c', count, '-i', '0.02',
                             '-W', '2', h2.IP())
            (folder / 'ping.txt').write_text(output)
            print(output)
            server = h2.popen(['iperf3', '-s', '-1'], stdout=serverlog,
                              stderr=serverlog)
            time.sleep(1)
            if server.poll() is not None:
                raise RuntimeError('iperf3 server failed; see iperf-server.log')
            # -R: h2 sends, h1 receives, so the transfer crosses the shaped s1 -> h1 port.
            output = checked(h1, 'iperf3', '-c', h2.IP(), '-t', '20', '-R', '-J')
            (folder / 'iperf.json').write_text(output)
            for port in s1_ports(net):
                output = checked(s1, 'tc', '-s', 'qdisc', 'show', 'dev', port)
                (folder / f'{port}-qdisc.txt').write_text(output)
        finally:
            stop_process(server)
            stop_process(capture)
    print(f'Measurements saved to {folder}; compare with README expectations.')


def build_config(args):
    cfg = dict(DEFAULTS)
    cfg.update(PROFILES[args.profile])
    for key in DEFAULTS:
        value = getattr(args, key)
        if value is not None:
            cfg[key] = value
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', choices=list(PROFILES), default='baseline')
    parser.add_argument('--test', action='store_true', help='capture measurements and exit')
    over = parser.add_argument_group('overrides (applied on top of --profile)')
    over.add_argument('--rtt-ms', dest='rtt_ms', type=float)
    over.add_argument('--bw-mbit', dest='bw_mbit', type=float)
    over.add_argument('--loss-pct', dest='loss_pct', type=float)
    over.add_argument('--loss-model', dest='loss_model', choices=['random', 'ge'])
    over.add_argument('--burst-len', dest='burst_len', type=float,
                      help='Gilbert-Elliott mean burst length in packets (default 3)')
    over.add_argument('--buffer-bdp', dest='buffer_bdp', type=float,
                      help='tbf buffer as a multiple of the bandwidth-delay product (default 1)')
    over.add_argument('--seed', type=int, help='netem PRNG seed (default 42)')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo /usr/bin/python3')
    cfg = build_config(args)

    from mininet.cli import CLI
    from mininet.net import Mininet
    from mininet.node import OVSSwitch

    folder = None
    if args.test:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder = Path(__file__).resolve().parent / 'results' / f'{stamp}-{args.profile}'
        folder.mkdir(parents=True)
    net = Mininet(topo=TwoHostTopo(), switch=OVSSwitch, controller=None,
                  autoSetMacs=True, autoStaticArp=True)
    try:
        net.start()
        # Warm up and validate without random loss before applying the profile.
        if net.pingAll() != 0:
            raise RuntimeError('Baseline connectivity failed')
        derived = configure(net, cfg)
        if args.test:
            (folder / 'config.json').write_text(
                json.dumps({'profile': args.profile, 'config': cfg, **derived}, indent=2))
            measure(net, cfg, folder)
        else:
            CLI(net)
    finally:
        net.stop()


if __name__ == '__main__':
    from mininet.log import setLogLevel
    setLogLevel('info')
    main()
