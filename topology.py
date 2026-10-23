#!/usr/bin/env python3
"""Two hosts and a standalone learning switch; isolated impairment profiles."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import signal
import subprocess
import time

from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo


class TwoHostTopo(Topo):
    def build(self):
        switch = self.addSwitch('s1', failMode='standalone')
        for number in (1, 2):
            host = self.addHost(f'h{number}', ip=f'10.0.0.{number}/24')
            self.addLink(host, switch)


topos = {'twohost': TwoHostTopo}


def checked(host, *args):
    out, err, code = host.pexec(list(args))
    if code:
        raise RuntimeError(f'{host.name}: {args}: {out}{err}')
    return out


def configure(net, profile):
    # Only host egress is shaped. Switch ports remain unmodified.
    h1, h2 = net.get('h1', 'h2')
    if profile == 'delay':
        for host in (h1, h2):
            checked(host, 'tc', 'qdisc', 'replace', 'dev', f'{host.name}-eth0',
                    'root', 'netem', 'delay', '50ms')
    elif profile == 'bandwidth':
        for host in (h1, h2):
            checked(host, 'tc', 'qdisc', 'replace', 'dev', f'{host.name}-eth0',
                    'root', 'tbf', 'rate', '10mbit', 'burst', '32kbit',
                    'latency', '400ms')
    elif profile == 'loss':
        checked(h1, 'tc', 'qdisc', 'replace', 'dev', 'h1-eth0',
                'root', 'netem', 'loss', 'random', '5%')


def stop_process(process):
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def measure(net, profile, folder):
    h1, h2 = net.get('h1', 'h2')
    # ARP and switch learning were warmed up before applying impairments.
    capture = server = None
    with (folder / 'tcpdump.log').open('w') as caplog, \
            (folder / 'iperf-server.log').open('w') as serverlog:
        try:
            capture = h2.popen(['tcpdump', '-i', 'h2-eth0', '-U', '-n',
                                '-s', '128', '-c', '10000', '-B', '4096',
                                '-w', str(folder / 'traffic.pcap'),
                                'icmp or tcp port 5201 or udp port 5201'],
                               stdout=caplog, stderr=caplog)
            time.sleep(1)
            if capture.poll() is not None:
                raise RuntimeError('tcpdump failed; see tcpdump.log')
            count = '1000' if profile == 'loss' else '20'
            output = checked(h1, 'ping', '-n', '-c', count, '-i', '0.02',
                             '-W', '2', h2.IP())
            (folder / 'ping.txt').write_text(output)
            print(output)
            server = h2.popen(['iperf3', '-s', '-1'], stdout=serverlog,
                              stderr=serverlog)
            time.sleep(1)
            if server.poll() is not None:
                raise RuntimeError('iperf3 server failed; see iperf-server.log')
            output = checked(h1, 'iperf3', '-c', h2.IP(), '-t', '20', '-J')
            (folder / 'iperf.json').write_text(output)
            for host in (h1, h2):
                output = checked(host, 'tc', '-s', 'qdisc', 'show',
                                 'dev', f'{host.name}-eth0')
                (folder / f'{host.name}-qdisc.txt').write_text(output)
        finally:
            stop_process(server)
            stop_process(capture)
    print(f'Measurements saved to {folder}; compare with README expectations.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['baseline', 'delay', 'bandwidth', 'loss'],
                        default='baseline')
    parser.add_argument('--test', action='store_true', help='capture measurements and exit')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo /usr/bin/python3')
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
        configure(net, args.profile)
        if args.test:
            measure(net, args.profile, folder)
        else:
            CLI(net)
    finally:
        net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
