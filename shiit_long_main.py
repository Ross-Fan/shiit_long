#!/usr/bin/env python3
"""
山寨币合约数据采集主程序
定时采集涨幅榜、动能数据和广场热度
"""

import asyncio
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from src.collectors.binance_market import BinanceMarketCollector, TickerData
from src.collectors.binance_square import BinanceSquareCollector
from src.collectors.momentum import MomentumCollector
from src.signal import SignalConfig, generate_signals_from_db
from src.storage import Database


# 配置
CONFIG = {
    "top_gainers_limit": 60,       # 涨幅榜数量
    "square_fetch_limit": 60,      # 广场热度抓取数量
    "square_delay": 3.0,           # 广场抓取间隔（秒）
    "momentum_concurrency": 10,    # 动能数据并发数
    "db_path": "data/shiit_long.db",
    "log_path": "logs/shiit_long.log",
    # 调度配置
    "fast_interval_minutes": 3,    # 快速任务间隔（涨幅榜+动能+信号）
    "slow_interval_minutes": 20,   # 慢速任务间隔（广场热度）
}

# 入场信号配置
SIGNAL_CONFIG = SignalConfig(
    max_rank=30,
    min_volume_ratio=0.5,
    min_price_ratio=1.0,
    min_discuss_count=0,
    min_view_count=0,
    min_price_change=3.0,
    max_price_change=30.0,
)


def setup_logger(log_path: str):
    """配置日志系统"""
    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
    )


class ShiitLongCollector:
    """山寨币数据采集器"""

    def __init__(self, config: dict = None):
        self.config = config or CONFIG
        self.db = Database(self.config["db_path"])
        self._running = False
        self._latest_gainers: List[TickerData] = []  # 缓存最新涨幅榜

    async def collect_fast(self):
        """
        快速采集任务（每3分钟）
        - 涨幅榜
        - 动能数据
        - 入场信号
        """
        snapshot_time = datetime.now()
        start_time = time.time()

        logger.info("-" * 50)
        logger.info(f"[快速采集] {snapshot_time.strftime('%H:%M:%S')}")
        logger.info("-" * 50)

        market_count = 0
        momentum_count = 0
        momentum_success = 0

        try:
            # Step 1: 获取涨幅榜
            logger.info(f"[1/3] 获取涨幅榜 Top {self.config['top_gainers_limit']}...")

            market_collector = BinanceMarketCollector()
            try:
                top_gainers = await market_collector.get_top_gainers(
                    self.config["top_gainers_limit"]
                )
                market_count = len(top_gainers)
                self._latest_gainers = top_gainers  # 缓存供广场热度使用

                self.db.save_market_snapshots(top_gainers, snapshot_time)

                top5_info = " | ".join(
                    [f"{t.base_asset}: {t.price_change_percent:+.2f}%" for t in top_gainers[:5]]
                )
                logger.info(f"Top5: {top5_info}")

            finally:
                await market_collector.close()

            # Step 2: 获取动能数据
            logger.info(f"[2/3] 获取动能数据...")

            trade_symbols = [t.symbol for t in top_gainers]

            momentum_collector = MomentumCollector()
            try:
                momentum_results = await momentum_collector.fetch_batch_momentum(
                    trade_symbols,
                    concurrency=self.config["momentum_concurrency"]
                )
                momentum_count = len(momentum_results)
                momentum_success = sum(1 for m in momentum_results if m.success)

                self.db.save_momentum_snapshots(momentum_results, snapshot_time)

                successful = [m for m in momentum_results if m.success]
                if successful:
                    top3 = sorted(successful, key=lambda x: x.momentum_score, reverse=True)[:3]
                    top3_info = " | ".join(
                        [f"{m.base_asset}: {m.volume_ratio:.1f}x" for m in top3]
                    )
                    logger.info(f"放量Top3: {top3_info}")

            finally:
                await momentum_collector.close()

            # Step 3: 生成入场信号
            logger.info("[3/3] 扫描入场信号...")
            signals = generate_signals_from_db(self.db, SIGNAL_CONFIG)

            if signals:
                self.db.save_entry_signals(signals)

                logger.warning("=" * 50)
                logger.warning(f"[SIGNAL] 发现 {len(signals)} 个入场信号!")
                logger.warning("=" * 50)

                for s in signals:
                    logger.warning(
                        f"[SIGNAL] {s.base_asset:<8} | "
                        f"涨幅: {s.price_change_percent:>5.1f}% | "
                        f"#{s.rank:<2} | "
                        f"放量: {s.volume_ratio:.1f}x | "
                        f"价格比: {s.price_ratio:.2f}x | "
                        f"{s.signal_strength}"
                    )

                logger.warning("=" * 50)
            else:
                logger.info("无入场信号")

        except Exception as e:
            logger.error(f"快速采集失败: {e}")

        duration = time.time() - start_time
        logger.info(f"[快速采集完成] 耗时: {duration:.1f}秒 | 市场: {market_count} | 动能: {momentum_count}")

    async def collect_slow(self):
        """
        慢速采集任务（每20分钟）
        - 广场热度
        """
        snapshot_time = datetime.now()
        start_time = time.time()

        logger.info("=" * 50)
        logger.info(f"[广场热度采集] {snapshot_time.strftime('%H:%M:%S')}")
        logger.info("=" * 50)

        square_count = 0
        square_success = 0

        try:
            # 使用缓存的涨幅榜数据
            if not self._latest_gainers:
                logger.warning("无涨幅榜缓存，先获取涨幅榜...")
                market_collector = BinanceMarketCollector()
                try:
                    self._latest_gainers = await market_collector.get_top_gainers(
                        self.config["top_gainers_limit"]
                    )
                finally:
                    await market_collector.close()

            fetch_limit = min(self.config["square_fetch_limit"], len(self._latest_gainers))
            symbols = [t.base_asset for t in self._latest_gainers[:fetch_limit]]

            logger.info(f"抓取 {fetch_limit} 个币种的广场热度...")

            square_collector = BinanceSquareCollector(
                delay=self.config["square_delay"]
            )
            try:
                hotness_results = await square_collector.fetch_batch_hotness(symbols)
                square_count = len(hotness_results)
                square_success = sum(1 for h in hotness_results if h.success)

                self.db.save_square_hotness(hotness_results, snapshot_time)

                # 显示热度最高的前3个
                successful = [h for h in hotness_results if h.success and h.discuss_count > 0]
                if successful:
                    top3 = sorted(successful, key=lambda x: x.discuss_count, reverse=True)[:3]
                    top3_info = " | ".join(
                        [f"{h.symbol}: {h.discuss_count:,}讨论" for h in top3]
                    )
                    logger.info(f"热度Top3: {top3_info}")

            finally:
                await square_collector.close()

        except Exception as e:
            logger.error(f"广场热度采集失败: {e}")

        duration = time.time() - start_time
        logger.info(f"[广场热度完成] 耗时: {duration:.1f}秒 | 成功: {square_success}/{square_count}")

    async def collect_once(self):
        """单次执行：同时运行快速和慢速任务"""
        await self.collect_fast()
        await self.collect_slow()

    async def run_scheduler(self):
        """启动定时调度器"""
        self._running = True

        scheduler = AsyncIOScheduler()

        fast_interval = self.config["fast_interval_minutes"]
        slow_interval = self.config["slow_interval_minutes"]

        # 快速任务：涨幅榜 + 动能 + 信号
        scheduler.add_job(
            self.collect_fast,
            trigger=IntervalTrigger(minutes=fast_interval),
            id="fast_job",
            name="快速采集(涨幅榜+动能+信号)",
            max_instances=1,
            coalesce=True,
        )

        # 慢速任务：广场热度
        scheduler.add_job(
            self.collect_slow,
            trigger=IntervalTrigger(minutes=slow_interval),
            id="slow_job",
            name="慢速采集(广场热度)",
            max_instances=1,
            coalesce=True,
        )

        scheduler.start()

        logger.info("=" * 60)
        logger.info("山寨币数据采集服务已启动")
        logger.info("=" * 60)
        logger.info(f"快速任务: 每 {fast_interval} 分钟 (涨幅榜+动能+信号)")
        logger.info(f"慢速任务: 每 {slow_interval} 分钟 (广场热度)")
        logger.info(f"数据库: {self.config['db_path']}")
        logger.info(f"日志: {self.config['log_path']}")
        logger.info("按 Ctrl+C 停止服务")
        logger.info("=" * 60)

        # 立即执行首次采集
        logger.info("执行首次采集...")
        await self.collect_fast()
        await self.collect_slow()

        # 保持运行
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            scheduler.shutdown()
            logger.info("调度器已停止")

    def stop(self):
        """停止服务"""
        self._running = False


# 全局实例
_collector: Optional[ShiitLongCollector] = None


def signal_handler(signum, frame):
    """处理退出信号"""
    logger.warning("收到退出信号，正在停止...")
    if _collector:
        _collector.stop()


async def main():
    """主函数"""
    global _collector

    run_once = "--once" in sys.argv

    # 解析参数
    for arg in sys.argv:
        if arg.startswith("--fast-interval="):
            try:
                CONFIG["fast_interval_minutes"] = int(arg.split("=")[1])
            except ValueError:
                print(f"无效参数: {arg}")
                sys.exit(1)
        elif arg.startswith("--slow-interval="):
            try:
                CONFIG["slow_interval_minutes"] = int(arg.split("=")[1])
            except ValueError:
                print(f"无效参数: {arg}")
                sys.exit(1)
        elif arg.startswith("--square-limit="):
            try:
                CONFIG["square_fetch_limit"] = int(arg.split("=")[1])
            except ValueError:
                print(f"无效参数: {arg}")
                sys.exit(1)

    setup_logger(CONFIG["log_path"])

    _collector = ShiitLongCollector(CONFIG)

    if run_once:
        await _collector.collect_once()
    else:
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
    --once                单次执行（快速+慢速任务都执行）
    --fast-interval=N     快速任务间隔（分钟），默认3
    --slow-interval=N     慢速任务间隔（分钟），默认20
    --square-limit=N      广场热度抓取数量，默认60
    --help                显示帮助

调度说明:
    快速任务（每3分钟）: 涨幅榜 + 动能数据 + 入场信号
    慢速任务（每20分钟）: 广场热度

示例:
    # 启动定时服务
    python shiit_long_main.py

    # 自定义间隔
    python shiit_long_main.py --fast-interval=5 --slow-interval=30

    # 单次执行
    python shiit_long_main.py --once

    # 后台运行
    nohup python3 shiit_long_main.py > /dev/null 2>&1 &

日志: logs/shiit_long.log
""")


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())
