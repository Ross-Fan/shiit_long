"""
测试脚本：获取涨幅榜Top50 + 抓取广场热度
"""

import asyncio
from src.collectors.binance_market import BinanceMarketCollector
from src.collectors.binance_square import BinanceSquareCollector


async def main():
    print("=" * 70)
    print("山寨币数据采集测试")
    print("=" * 70)

    # Step 1: 获取涨幅榜 Top 50
    print("\n[Step 1] 获取涨幅榜 Top 50...")
    print("-" * 70)

    market_collector = BinanceMarketCollector()
    try:
        top_gainers = await market_collector.get_top_gainers(50)
        print(f"获取到 {len(top_gainers)} 个币种\n")

        # 显示前10
        print(f"{'排名':<4} {'币种':<10} {'涨幅':<10}")
        for i, t in enumerate(top_gainers[:10], 1):
            print(f"{i:<4} {t.base_asset:<10} {t.price_change_percent:>7.2f}%")
        print("...")

    finally:
        await market_collector.close()

    # Step 2: 抓取广场热度（取前5个测试，节省时间）
    print("\n[Step 2] 抓取广场热度 (前5个币种，3秒间隔)...")
    print("-" * 70)

    symbols = [t.base_asset for t in top_gainers[:5]]

    # 3秒延迟，顺序执行
    square_collector = BinanceSquareCollector(delay=3.0)
    try:
        hotness_results = await square_collector.fetch_batch_hotness(symbols)
    finally:
        await square_collector.close()

    # Step 3: 合并结果
    print("\n" + "=" * 70)
    print("[Step 3] 合并数据")
    print("=" * 70)

    # 创建热度映射
    hotness_map = {h.symbol: h for h in hotness_results}

    print(f"{'排名':<4} {'币种':<10} {'涨幅':<10} {'状态':<6} {'浏览量':<15} {'讨论数':<10}")
    print("-" * 65)

    for i, t in enumerate(top_gainers[:5], 1):
        hotness = hotness_map.get(t.base_asset)
        if hotness and hotness.success:
            status = "成功"
            print(f"{i:<4} {t.base_asset:<10} {t.price_change_percent:>7.2f}% "
                  f"{status:<6} {hotness.view_count:>12,} {hotness.discuss_count:>10,}")
        elif hotness:
            status = "失败"
            print(f"{i:<4} {t.base_asset:<10} {t.price_change_percent:>7.2f}% "
                  f"{status:<6} {'N/A':>12} {'N/A':>10}")
        else:
            print(f"{i:<4} {t.base_asset:<10} {t.price_change_percent:>7.2f}% "
                  f"{'无数据':<6} {'N/A':>12} {'N/A':>10}")

    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
