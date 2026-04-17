"""
币安广场热度采集器
按币种抓取 hashtag 页面的热度数据
"""

import asyncio
import re
from dataclasses import dataclass
from typing import List, Optional
from playwright.async_api import async_playwright, Browser
from loguru import logger


# 特殊值标记
FETCH_FAILED = -1       # 抓取失败
PARSE_FAILED = -999     # 解析失败


@dataclass
class SquareHotness:
    """广场热度数据"""
    symbol: str              # 币种代码，如 PEPE
    view_count: int          # 话题浏览量 (-1表示抓取失败)
    discuss_count: int       # 话题讨论数 (-1表示抓取失败)
    hotness_score: float     # 综合热度评分 (-1表示抓取失败)
    success: bool            # 是否抓取成功


class BinanceSquareCollector:
    """币安广场热度采集器"""

    BASE_URL = "https://www.binance.com/en/square/hashtag"

    def __init__(self, delay: float = 3.0):
        """
        Args:
            delay: 每次请求间隔（秒），默认3秒
        """
        self._browser: Optional[Browser] = None
        self._playwright = None
        self._delay = delay

    async def _ensure_browser(self):
        """确保浏览器已启动"""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)

    async def close(self):
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def _parse_count(self, text: str) -> int:
        """
        解析数字文本，支持 K, M, B 后缀
        例如: "1.2K" -> 1200, "96.6M" -> 96600000
        """
        if not text:
            return 0

        text = text.strip().upper().replace(',', '')

        # 匹配数字和后缀
        match = re.match(r'^([\d.]+)\s*([KMB])?', text)
        if not match:
            return 0

        try:
            number = float(match.group(1))
        except ValueError:
            return 0

        suffix = match.group(2)

        if suffix == 'K':
            return int(number * 1000)
        elif suffix == 'M':
            return int(number * 1000000)
        elif suffix == 'B':
            return int(number * 1000000000)
        else:
            return int(number)

    async def fetch_symbol_hotness(self, symbol: str) -> SquareHotness:
        """
        获取单个币种的广场热度

        Args:
            symbol: 币种代码，如 PEPE

        Returns:
            SquareHotness（抓取失败时 success=False，数值为-1）
        """
        await self._ensure_browser()

        url = f"{self.BASE_URL}/{symbol}"
        page = await self._browser.new_page()

        try:
            page.set_default_timeout(20000)
            await page.goto(url, wait_until='domcontentloaded')
            await asyncio.sleep(2)  # 等待JS渲染

            # 获取页面文本
            body_text = await page.inner_text('body')

            view_count = 0
            discuss_count = 0

            # 解析 views: 匹配 "96.6M views" 或 "1,234 views"
            view_match = re.search(r'([\d,.]+[KMB]?)\s*views?', body_text, re.IGNORECASE)
            if view_match:
                view_count = self._parse_count(view_match.group(1))

            # 解析 discussing: 匹配 "93,321 Discussing"
            discuss_match = re.search(r'([\d,.]+[KMB]?)\s*Discussing', body_text, re.IGNORECASE)
            if discuss_match:
                discuss_count = self._parse_count(discuss_match.group(1))

            # 计算热度评分
            # view 权重较低（数值大），discuss 权重高
            hotness_score = view_count * 0.00001 + discuss_count * 1.0

            return SquareHotness(
                symbol=symbol,
                view_count=view_count,
                discuss_count=discuss_count,
                hotness_score=hotness_score,
                success=True
            )

        except Exception as e:
            logger.warning(f"{symbol} 抓取失败: {e}")
            return SquareHotness(
                symbol=symbol,
                view_count=FETCH_FAILED,
                discuss_count=FETCH_FAILED,
                hotness_score=FETCH_FAILED,
                success=False
            )

        finally:
            await page.close()

    async def fetch_batch_hotness(self, symbols: List[str]) -> List[SquareHotness]:
        """
        批量获取多个币种的广场热度（顺序执行，无并发）

        Args:
            symbols: 币种列表

        Returns:
            SquareHotness 列表（保持输入顺序）
        """
        results = []
        total = len(symbols)

        for i, symbol in enumerate(symbols):
            logger.debug(f"[{i+1}/{total}] 抓取 {symbol}...")

            result = await self.fetch_symbol_hotness(symbol)
            results.append(result)

            if result.success:
                logger.debug(f"{symbol}: views={result.view_count:,}, discuss={result.discuss_count:,}")
            else:
                logger.debug(f"{symbol}: 抓取失败")

            # 延迟，避免被封
            if i < total - 1:  # 最后一个不需要延迟
                await asyncio.sleep(self._delay)

        return results


async def main():
    """测试函数"""
    # 测试几个币种
    test_symbols = ['PEPE', 'WIF', 'BONK', 'DOGE']

    # 设置3秒延迟
    collector = BinanceSquareCollector(delay=3.0)

    try:
        print("=" * 60)
        print("币安广场热度采集测试")
        print("=" * 60)
        print()

        results = await collector.fetch_batch_hotness(test_symbols)

        print()
        print("=" * 60)
        print("采集结果")
        print("=" * 60)
        print(f"{'币种':<8} {'状态':<6} {'浏览量':<15} {'讨论数':<12} {'热度评分':<12}")
        print("-" * 55)

        success_count = 0
        for item in results:
            status = "成功" if item.success else "失败"
            if item.success:
                success_count += 1
                print(f"{item.symbol:<8} {status:<6} {item.view_count:>12,} {item.discuss_count:>10,} "
                      f"{item.hotness_score:>12,.2f}")
            else:
                print(f"{item.symbol:<8} {status:<6} {item.view_count:>12} {item.discuss_count:>10} "
                      f"{item.hotness_score:>12}")

        print("-" * 55)
        print(f"成功: {success_count}/{len(test_symbols)}")

    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
