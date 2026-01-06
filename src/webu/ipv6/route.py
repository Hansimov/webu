import argparse
import netifaces
import re

import time

from pathlib import Path

from tclogger import TCLogger, logstr
from tclogger import PathType, decolored, shell_cmd


logger = TCLogger(name="IPv6RouteUpdater")


NDPDD_CONF = "/etc/ndppd.conf"


class IPv6Prefixer:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.interfaces = []
        self._init_network_interfaces()
        self._init_prefix()

    def _get_prefix_from_addr_netmask(self, addr: str, netmask: str) -> tuple[str, int]:
        # netmask "ffff:ffff:ffff:ffff::/64" means 64-bit prefix (4 groups)
        prefix_bits = netmask.count("f") * 4
        # each group is 16 bits, sep by ":"
        num_groups = prefix_bits // 16
        addr_groups = addr.split(":")
        prefix = ":".join(addr_groups[:num_groups])
        return prefix, prefix_bits

    def _init_network_interfaces(self):
        interfaces = netifaces.interfaces()
        for interface in interfaces:
            addresses = netifaces.ifaddresses(interface)
            if netifaces.AF_INET6 not in addresses:
                continue
            if interface.lower().startswith("cloudflare"):
                # skip cloudflare tunnel interface
                continue
            for addr_info in addresses[netifaces.AF_INET6]:
                if not addr_info["addr"].startswith("2"):
                    break
                addr = addr_info["addr"]
                netmask = addr_info.get("netmask") or addr_info.get("mask")
                prefix, prefix_bits = self._get_prefix_from_addr_netmask(addr, netmask)
                self.interfaces.append(
                    {
                        "interface": interface,
                        "addr": addr,
                        "netmask": netmask,
                        "prefix": prefix,
                        "prefix_bits": prefix_bits,
                    }
                )

    def _init_prefix(self):
        interface = self.interfaces[0]
        netint = interface["interface"]
        prefix = interface["prefix"].strip(":")
        prefix_bits = interface["prefix_bits"]
        if self.verbose:
            prefix_str = logstr.okay(f"[{prefix}]")
            prefix_bits_str = logstr.mesg(f"(/{prefix_bits})")
            netint_str = logstr.file(f"{netint}")
            logger.note(
                f"> IPv6 prefix: {prefix_str} {prefix_bits_str} on {netint_str}"
            )
        self.netint = netint
        self.prefix = prefix
        self.prefix_bits = prefix_bits

    def _addr_suffix(self, addr: str) -> str:
        """Extract suffix part of addr for shorter logging."""
        if self.prefix and addr.startswith(self.prefix):
            return addr[len(self.prefix) :]
        return addr


class IPv6RouteUpdater:
    """Update route and ndppd.conf for IPv6 proxying."""

    def __init__(self, ndppd_conf: PathType = None, verbose: bool = False):
        self.ndppd_conf = ndppd_conf or Path(NDPDD_CONF)
        self.prefixer = IPv6Prefixer()
        self.prefix = self.prefixer.prefix
        self.netint = self.prefixer.netint
        self.verbose = verbose

    def is_ndppd_conf_latest(self):
        logger.note("> Check proxy (netint) and rule (prefix) in ndppd.conf:")
        if not self.ndppd_conf.exists():
            logger.mesg(f"ndppd.conf does not exist: {self.ndppd_conf}")
            return False

        with open(self.ndppd_conf, "r") as rf:
            lines = rf.readlines()

        is_netint_found = False
        netint_pattern = re.compile(rf"proxy\s+{self.netint}")
        for line in lines:
            if netint_pattern.search(line):
                netint_str = logstr.file(self.netint)
                logger.mesg(f"  + Found proxy (netint): {netint_str}")
                is_netint_found = True
                break
        if not is_netint_found:
            logger.mesg(f"  - Not found proxy (netint): {netint_str}")
            return False

        is_prefix_found = False
        prefix_pattern = re.compile(rf"rule\s+{self.prefix}::/64")
        prefix_str = None
        for line in lines:
            if prefix_pattern.search(line):
                prefix_str = logstr.file(f"{self.prefix}::/64")
                logger.mesg(f"  + Found rule (prefix/): {prefix_str}")
                is_prefix_found = True
                break
        if not is_prefix_found:
            logger.mesg(f"  - Not found rule (prefix/): {prefix_str}")
            return False
        return True

    def add_route(self):
        logger.note("> Add IP route:")
        cmd = f"sudo ip route add local {self.prefix}::/64 dev {self.netint}"
        shell_cmd(cmd)

    def del_route(self):
        logger.note("> Delete IP route:")
        cmd = f"sudo ip route del local {self.prefix}::/64 dev {self.netint}"
        shell_cmd(cmd)

    def modify_ndppd_conf(self, overwrite: bool = False):
        if self.ndppd_conf.exists():
            with open(self.ndppd_conf, "r") as rf:
                old_ndppd_conf_str = rf.read()
            logger.note(f"> Read: {logstr.file(self.ndppd_conf)}")
            logger.mesg(f"{old_ndppd_conf_str}")

        if not self.ndppd_conf.exists() or overwrite:
            new_ndppd_conf_str = (
                f"route-ttl 30000\n"
                f"proxy {logstr.success(self.netint)} {{\n"
                f"    router no\n"
                f"    timeout 500\n"
                f"    ttl 30000\n"
                f"    rule {logstr.success(self.prefix)}::/64 {{\n"
                f"        static\n"
                f"    }}\n"
                f"}}\n"
            )
            logger.note(f"> Write: {logstr.file(self.ndppd_conf)}")
            logger.mesg(f"{new_ndppd_conf_str}")
            with open(self.ndppd_conf, "w") as wf:
                wf.write(decolored(new_ndppd_conf_str))
            logger.okay(f"✓ Modified: {logstr.file(self.ndppd_conf)}")

    def restart_ndppd(self):
        logger.note("> Restart ndppd:")
        cmd = "sudo systemctl restart ndppd"
        shell_cmd(cmd)
        logger.okay(f"✓ Restarted: {logstr.file('ndppd')}")

    def wait_ndppd_work(self, wait_seconds: int = 5):
        logger.note(f"> Waiting {wait_seconds} seconds for ndppd to work ...")
        time.sleep(wait_seconds)

    def run(self):
        self.add_route()
        if self.is_ndppd_conf_latest():
            logger.okay(f"✓ ndppd.conf is up-to-date, skip restart.")
        else:
            self.modify_ndppd_conf(overwrite=True)
            self.restart_ndppd()
            self.wait_ndppd_work()


class IPv6Argparser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument(
            "-nc",
            "--ndppd-conf",
            type=str,
            help=f"ndppd.conf path (default: {NDPDD_CONF})",
            default=None,
        )

        self.args = self.parse_args()


def main():
    args = IPv6Argparser().args
    modifier = IPv6RouteUpdater(ndppd_conf=args.ndppd_conf, verbose=True)
    modifier.run()


if __name__ == "__main__":
    main()

    # sudo is needed to modify ndppd.conf

    # Case1: Run directly, need to type sudo password
    # sudo env "PATH=$PATH" python -m webu.ipv6.route -r

    # Case2: Run with piped password
    # echo $SUDOPASS | sudo -S env "PATH=$PATH" python -m webu.ipv6.route -r
