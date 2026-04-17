#!/usr/bin/env python3
"""
山寨币合约数据采集主程序
定时采集涨幅榜和广场热度数据
"""

import asyncio
import signal
import sys
import time
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.collectors.binance_market import BinanceMarketCollector
from src.collectors.binance_square import BinanceSquareCollector
from src.storage import Database


# 配置
CONFIG = {
    "top_gainers_limit": 50,       # 涨幅榜数量
    "square_fetch_limit": 20,      # 广场热度抓取数量（前N个）
    "square_delay": 3.0,           # 广场抓取间隔（秒）
    "schedule_interval_minutes": 15,  # 定时执行间隔（分钟）
    "db_path": "data/shiit_long.db",  # 数据库路径
}


class ShiitLongCollector:
    """山寨币数据采集器"""

    def __init__(self, config: dict = None):
        self.config = config or CONFIG
        self.db = Database(self.config["db_path"])
        self._running = False

    async def collect_once(self) -> dict:
        """
        执行一次完整的数据采集

        Returns:
            采集结果统计
        """
        snapshot_time = datetime.now()
        start_time = time.time()

        print()
        print("=" * 70)
        print(f"[{snapshot_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始数据采集")
        print("=" * 70)

        market_count = 0
        square_count = 0
        square_success = 0
        error_message = None
        status = "success"

        try:
            # Step 1: 获取涨幅榜
            print(f"\n[1/2] 获取涨幅榜 Top {self.config['top_gainers_limit']}...")
            print("-" * 50)

            market_collector = BinanceMarketCollector()
            try:
                top_gainers = await market_collector.get_top_gainers(
                    self.config["top_gainers_limit"]
                )
                market_count = len(top_gainers)
                print(f"获取到 {market_count} 个币种")

                # 保存到数据库
                self.db.save_market_snapshots(top_gainers, snapshot_time)
                print(f"已保存到数据库")

                # 显示前5
                print(f"\n{'排名':<4} {'币种':<10} {'涨幅':<10}")
                for i, t in enumerate(top_gainers[:5], 1):
                    print(f"{i:<4} {t.base_asset:<10} {t.price_change_percent:>7.2f}%")
                if market_count > 5:
                    print("...")

            finally:
                await market_collector.close()

            # Step 2: 抓取广场热度
            fetch_limit = min(self.config["square_fetch_limit"], market_count)
            print(f"\n[2/2] 抓取广场热度 (前 {fetch_limit} 个币种)...")
            print("-" * 50)

            symbols = [t.base_asset for t in top_gainers[:fetch_limit]]

            square_collector = BinanceSquareCollector(
                delay=self.config["square_delay"]
            )
            try:
                hotness_results = await square_collector.fetch_batch_hotness(symbols)
                square_count = len(hotness_results)
                square_success = sum(1 for h in hotness_results if h.success)

                # 保存到数据库
                self.db.save_square_hotness(hotness_results, snapshot_time)
                print(f"\n已保存 {square_count} 条热度数据 (成功: {square_success})")

            finally:
                await square_collector.close()

        except Exception as e:
            status = "error"
            error_message = str(e)
            print(f"\n[错误] 采集失败: {e}")

        # 计算耗时
        duration = time.time() - start_time

        # 记录采集日志
        self.db.log_collection(
            snapshot_time=snapshot_time,
            market_count=market_count,
            square_count=square_count,
            square_success=square_success,
            duration_seconds=duration,
            status=status,
            error_message=error_message
        )

        # 输出统计
        print()
        print("=" * 70)
        print(f"采集完成 | 耗时: {duration:.1f}秒 | 状态: {status}")
        print(f"市场数据: {market_count} 条 | 热度数据: {square_count} 条 (成功 {square_success})")
        print("=" * 70)

        return {
            "snapshot_time": snapshot_time,
            "market_count": market_count,
            "square_count": square_count,
            "square_success": square_success,
            "duration": duration,
            "status": status
        }

    async def run_scheduler(self):
        """启动定时调度器"""
        self._running = True

        # 创建调度器
        scheduler = AsyncIOScheduler()

        # 添加定时任务
        interval_minutes = self.config["schedule_interval_minutes"]
        scheduler.add_job(
            self.collect_once,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="collect_job",
            name="数据采集任务",
            max_instances=1,  # 防止任务堆积
            coalesce=True,    # 错过的任务合并执行
        )

        # 启动调度器
        scheduler.start()

        print()
        print("=" * 70)
        print("山寨币数据采集服务已启动")
        print("=" * 70)
        print(f"执行间隔: 每 {interval_minutes} 分钟")
        print(f"数据库: {self.config['db_path']}")
        print(f"涨幅榜数量: {self.config['top_gainers_limit']}")
        print(f"热度抓取数量: {self.config['square_fetch_limit']}")
        print("-" * 70)
        print("按 Ctrl+C 停止服务")
        print("=" * 70)

        # 立即执行一次
        print("\n[启动] 立即执行首次采集...")
        await self.collect_once()

        # 保持运行
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            scheduler.shutdown()
            print("\n调度器已停止")

    def stop(self):
        """停止服务"""
        self._running = False


# 全局实例，用于信号处理
_collector: Optional[ShiitLongCollector] = None


def signal_handler(signum, frame):
    """处理退出信号"""
    print("\n\n收到退出信号，正在停止...")
    if _collector:
        _collector.stop()


async def main():
    """主函数"""
    global _collector

    # 解析命令行参数
    run_once = "--once" in sys.argv

    # 自定义间隔
    for arg in sys.argv:
        if arg.startswith("--interval="):
            try:
                CONFIG["schedule_interval_minutes"] = int(arg.split("=")[1])
            except ValueError:
                print(f"无效的间隔参数: {arg}")
                sys.exit(1)

    # 自定义热度抓取数量
    for arg in sys.argv:
        if arg.startswith("--square-limit="):
            try:
                CONFIG["square_fetch_limit"] = int(arg.split("=")[1])
            except ValueError:
                print(f"无效的热度数量参数: {arg}")
                sys.exit(1)

    _collector = ShiitLongCollector(CONFIG)

    if run_once:
        # 单次执行模式
        await _collector.collect_once()
    else:
        # 定时执行模式
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        await _collector.run_scheduler()


def print_usage():
    """打印使用说明"""
    print("""
山寨币数据采集主程序

用法:
    python shiit_long_main.py [选项]

选项:
    --once              单次执行模式（不启动定时任务）
    --interval=N        设置执行间隔（分钟），默认15
    --square-limit=N    设置热度抓取数量，默认20
    --help              显示此帮助信息

示例:
    # 启动定时服务（每15分钟执行）
    python shiit_long_main.py

    # 每30分钟执行一次
    python shiit_long_main.py --interval=30

    # 只执行一次
    python shiit_long_main.py --once

    # 抓取前10个币种的热度
    python shiit_long_main.py --square-limit=10

    # 后台运行
    nohup python shiit_long_main.py > logs/shiit_long.log 2>&1 &
""")


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())
