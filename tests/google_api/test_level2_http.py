"""测试新的 HTTP-based Level-2 实现。

用 self-built 代理 (127.0.0.1:11111 和 11119) 验证:
1. check_level2_single() — 单个代理检测
2. check_level2_batch() — 批量检测
"""

import asyncio

from webu.google_api.checker import check_level2_single, check_level2_batch


SELF_BUILT_PROXIES = [
    {"ip": "127.0.0.1", "port": 11111, "protocol": "http"},
    {"ip": "127.0.0.1", "port": 11119, "protocol": "http"},
]


async def test_single():
    """测试 check_level2_single。"""
    print("=" * 60)
    print("Test: check_level2_single")
    print("=" * 60)

    for proxy in SELF_BUILT_PROXIES:
        print(f"\n  Testing {proxy['ip']}:{proxy['port']} ...")
        result = await check_level2_single(
            ip=proxy["ip"],
            port=proxy["port"],
            protocol=proxy["protocol"],
            timeout_s=15,
        )
        status = "PASS" if result["is_valid"] else "FAIL"
        print(f"    Result: {status}")
        print(f"    Latency: {result['latency_ms']}ms")
        if result["last_error"]:
            print(f"    Error: {result['last_error']}")
        assert result["check_level"] == 2
        assert result["is_valid"], f"Expected PASS for {proxy['ip']}:{proxy['port']}"

    print("\n  ✓ All single tests PASSED")


async def test_batch():
    """测试 check_level2_batch。"""
    print("\n" + "=" * 60)
    print("Test: check_level2_batch")
    print("=" * 60)

    results = await check_level2_batch(
        SELF_BUILT_PROXIES,
        timeout_s=15,
        concurrency=10,
        verbose=True,
    )

    assert len(results) == len(SELF_BUILT_PROXIES)
    valid_count = sum(1 for r in results if r["is_valid"])
    print(f"\n  Results: {valid_count}/{len(results)} passed")

    for r in results:
        status = "PASS" if r["is_valid"] else "FAIL"
        print(f"    {r['ip']}:{r['port']} → {status} (latency={r['latency_ms']}ms)")
        if r["last_error"]:
            print(f"      error: {r['last_error']}")

    assert valid_count == len(SELF_BUILT_PROXIES), (
        f"Expected all {len(SELF_BUILT_PROXIES)} to pass, got {valid_count}"
    )
    print("\n  ✓ Batch test PASSED")


async def test_dead_proxy():
    """测试死代理是否正确 FAIL。"""
    print("\n" + "=" * 60)
    print("Test: dead proxy should FAIL")
    print("=" * 60)

    result = await check_level2_single(
        ip="127.0.0.1",
        port=9999,
        protocol="http",
        timeout_s=10,
    )
    print(f"  Result: {'PASS' if result['is_valid'] else 'FAIL'}")
    print(f"  Error: {result['last_error']}")
    assert not result["is_valid"], "Dead proxy should FAIL"
    print("  ✓ Dead proxy correctly FAILED")


async def main():
    await test_single()
    await test_batch()
    await test_dead_proxy()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
