import json
import threading
import netifaces
import random
import re
import requests
import requests.packages.urllib3.util.connection as urllib3_cn
import socket
import time

from pathlib import Path
from requests.adapters import HTTPAdapter
from tclogger import TCLogger, logstr
from tclogger import PathType, decolored, shell_cmd, get_now_str
from typing import Union

REQUESTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0 Safari/537.36"
}

logger = TCLogger(name="IPv6Utils")


class IPv6Adapter(HTTPAdapter):
    def __init__(self, source_address, *args, **kwargs):
        self.source_address = source_address
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["source_address"] = self.source_address
        return super().init_poolmanager(*args, **kwargs)


class RequestsSessionIPv6Adapter:
    @staticmethod
    def force_ipv4():
        urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

    @staticmethod
    def force_ipv6():
        if urllib3_cn.HAS_IPV6:
            urllib3_cn.allowed_gai_family = lambda: socket.AF_INET6

    def adapt(self, session: requests.Session, ip: str):
        try:
            socket.inet_pton(socket.AF_INET6, ip)
        except Exception as e:
            raise ValueError(f"× Invalid IPv6 format: [{ip}]")

        adapter = IPv6Adapter((ip, 0))
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session


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


class IPv6Pool:
    def __init__(self, verbose: bool = False):
        self.lock = threading.Lock()
        self.using_addrs = set()
        self.verbose = verbose

    def push_addr_to_using(self, addr: str):
        with self.lock:
            self.using_addrs.add(addr)

    def pop_addr_from_using(self, addr: str):
        with self.lock:
            self.using_addrs.discard(addr)

    def is_addr_using(self, addr: str) -> bool:
        with self.lock:
            return addr in self.using_addrs


class IPv6Cacher:
    def __init__(
        self, cache_dir: PathType = None, cache_name: str = None, verbose: bool = False
    ):
        self.cache_dir = cache_dir
        self.cache_name = cache_name
        self.verbose = verbose
        self.lock = threading.Lock()
        self.init_paths()

    def init_paths(self):
        self.cache_dir = Path(self.cache_dir or ".")
        cache_name = self.cache_name or "ipv6_addrs_cache"
        self.cache_path = (self.cache_dir / cache_name).with_suffix(".json")

    def is_cache_exists(self) -> bool:
        return self.cache_path.exists()

    def read_cache(self) -> list[dict]:
        with open(self.cache_path, "r", encoding="utf-8") as rf:
            cache_data: list[dict] = json.load(rf)
        return cache_data

    def write_cache(self, cache_data: list[dict]):
        with open(self.cache_path, "w", encoding="utf-8") as wf:
            json.dump(cache_data, wf, ensure_ascii=False, indent=4)

    def push_addr_to_cache(self, addr: str):
        with self.lock:
            logger.mesg(f"  + Push addr to cache: [{addr}]", verbose=self.verbose)
            if not self.is_cache_exists():
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_data: list[dict] = []
            else:
                cache_data: list[dict] = self.read_cache()
            addr_item = {
                "addr": addr,
                "cache_at": get_now_str(),
            }
            cache_data.append(addr_item)
            self.write_cache(cache_data)

    def pop_addr_from_cache(self, addr: str):
        with self.lock:
            logger.warn(f"  - Pop addr from cache: [{addr}]", verbose=self.verbose)
            if not self.is_cache_exists() or not addr:
                return
            cache_data: list[dict] = self.read_cache()
            cache_data = [item for item in cache_data if item.get("addr") != addr]
            self.write_cache(cache_data)

    def addr_to_segs(self, prefix: str, addr: str):
        addr_segs = addr.split(":")
        prefix_segs = prefix.split(":")
        suffix_segs = addr_segs[len(prefix_segs) :]
        return addr_segs, prefix_segs, suffix_segs

    def get_cache_addr(
        self, prefix: str, return_segs: bool = False, pool: IPv6Pool = None
    ) -> Union[str, tuple[str, list[str], list[str]]]:
        if not self.is_cache_exists():
            return None

        cache_data = self.read_cache()

        # filter using_addrs in pool from cache_data
        if pool and pool.using_addrs:
            filtered_cache_data = [
                item
                for item in cache_data
                if not pool.is_addr_using(item.get("addr", ""))
            ]
            if not filtered_cache_data:
                return None
        else:
            filtered_cache_data = cache_data

        # pick a random valid addr
        addr: str = None
        random.shuffle(filtered_cache_data)
        for item in filtered_cache_data:
            addr = item.get("addr", "")
            if addr.startswith(prefix):
                break

        if not addr:
            return None

        if pool:
            pool.push_addr_to_using(addr)

        if return_segs:
            _, prefix_segs, suffix_segs = self.addr_to_segs(prefix, addr)
            return addr, prefix_segs, suffix_segs
        else:
            return addr


class IPv6Checker:
    def __init__(self, timeout: float = 10, verbose: bool = False):
        self.adapter = RequestsSessionIPv6Adapter()
        self.session = requests.Session()
        self.timeout = timeout
        self.verbose = verbose

    def check(self, addr: str) -> bool:
        self.adapter.adapt(self.session, addr)
        response = self.session.get(
            "https://test.ipw.cn", headers=REQUESTS_HEADERS, timeout=self.timeout
        )
        addr_hash = addr.replace(":", "")
        resp_text = response.text.strip()
        resp_hash = resp_text.replace(":", "")
        is_good = addr_hash == resp_hash
        if self.verbose:
            if is_good:
                logger.okay(f"  ✓ [{resp_text}]")
            else:
                logger.warn(f"  x [{resp_text}]")
        return is_good


class IPv6Randomizer:
    def __init__(
        self,
        cacher: IPv6Cacher = None,
        checker: IPv6Checker = None,
        verbose: bool = False,
    ):
        self.cacher = cacher
        self.checker = checker
        self.verbose = verbose

    def get_random_addr_segs(self, prefix: str) -> tuple[str, list[str], list[str]]:
        prefix_segs = prefix.split(":")
        suffix_seg_count = 8 - len(prefix_segs)
        suffix_segs = [f"{random.randint(1, 65535):x}" for _ in range(suffix_seg_count)]
        addr = ":".join(prefix_segs + suffix_segs)
        return addr, prefix_segs, suffix_segs

    def get_random_addr(
        self,
        prefix: str,
        return_segs: bool = False,
        is_check: bool = True,
        max_retries: int = 5,
        is_cache_addr: bool = True,
        pool: IPv6Pool = None,
    ) -> Union[str, tuple[str, list[str], list[str]]]:
        if is_check and self.checker:
            retry_idx = 0
            is_valid = False
            while retry_idx < max_retries and not is_valid:
                addr, prefix_segs, suffix_segs = self.get_random_addr_segs(prefix)
                is_valid = self.checker.check(addr)
                if is_valid:
                    break
                retry_idx += 1
        else:
            addr, prefix_segs, suffix_segs = self.get_random_addr_segs(prefix)
            is_valid = True

        if not is_valid:
            logger.warn(f"  x [{addr}]")
            return None
        else:
            if is_cache_addr and self.cacher:
                self.cacher.push_addr_to_cache(addr)
            if pool:
                pool.push_addr_to_using(addr)
            if return_segs:
                return addr, prefix_segs, suffix_segs
            else:
                return addr


class IPv6Generator:
    def __init__(self, cache_name: str = None, verbose: bool = False):
        self.prefixer = IPv6Prefixer(verbose=verbose)
        self.pool = IPv6Pool(verbose=verbose)
        self.cacher = IPv6Cacher(cache_name=cache_name, verbose=verbose)
        self.checker = IPv6Checker(verbose=verbose)
        self.randomizer = IPv6Randomizer(
            cacher=self.cacher, checker=self.checker, verbose=verbose
        )
        self.lock = threading.Lock()
        self.verbose = verbose

    def generate(
        self,
        return_segs: bool = False,
        is_use_cache: bool = True,
        is_cache_addr: bool = True,
    ) -> Union[str, tuple[str, list[str], list[str]]]:
        with self.lock:
            prefix = self.prefixer.prefix
            if is_use_cache:
                cache_res = self.cacher.get_cache_addr(
                    prefix=prefix, return_segs=return_segs, pool=self.pool
                )
                if cache_res:
                    return cache_res

            random_res = self.randomizer.get_random_addr(
                prefix=prefix,
                return_segs=return_segs,
                is_cache_addr=is_cache_addr,
                pool=self.pool,
            )
            return random_res


class IPv6RouteModifier:
    def __init__(self, ndppd_conf: Union[Path, str] = None, verbose: bool = False):
        self.ndppd_conf = ndppd_conf or Path("/etc/ndppd.conf")
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


def test_ipv6_generator():
    generator = IPv6Generator(cache_name="ipv6_addrs_for_tags", verbose=True)
    checker = IPv6Checker(verbose=True)
    for i in range(50):
        ipv6, prefix_segs, suffix_segs = generator.generate(
            return_segs=True, is_use_cache=False, is_cache_addr=True
        )
        prefix = ":".join(prefix_segs)
        suffix = ":".join(suffix_segs)
        suffix_str = logstr.file(suffix)
        logger.note(f"  > [{prefix}:{suffix_str}]")
        checker.check(ipv6)

    logger.note(f"> using_addrs:")
    for addr in generator.pool.using_addrs:
        logger.file(f"  * [{addr}]")


def test_ipv6_route_modifier():
    modifier = IPv6RouteModifier()
    modifier.add_route()
    if modifier.is_ndppd_conf_latest():
        logger.okay(f"✓ ndppd.conf is up-to-date, skip restart.")
    else:
        modifier.modify_ndppd_conf(overwrite=True)
        modifier.restart_ndppd()
        modifier.wait_ndppd_work(wait_seconds=5)


if __name__ == "__main__":
    test_ipv6_generator()
    test_ipv6_route_modifier()

    # sudo is needed to modify ndppd.conf

    # Case1: Run directly, need to type sudo password
    # sudo env "PATH=$PATH" python -m networks.ipv6.router

    # Case2: Run with piped password
    # echo $SUDOPASS | sudo -S env "PATH=$PATH" python -m networks.ipv6.router
