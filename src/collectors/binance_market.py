"""
Binance Futures 行情数据采集器
获取24h涨幅榜Top50
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional
import aiohttp


@dataclass
class TickerData:
    """24h行情数据"""
    symbol: str              # 交易对，如 PEPEUSDT
    base_asset: str          # 基础资产，如 PEPE
    price: float             # 当前价格
    price_change_percent: float  # 24h涨跌幅 (%)
    volume: float            # 24h成交量
    quote_volume: float      # 24h成交额 (USDT)


class BinanceMarketCollector:
    """Binance Futures 行情采集器"""

    BASE_URL = "https://fapi.binance.com"

    # 排除的主流币
    EXCLUDE_MAJORS = {
        'BTC', 'ETH', 'BNB', 'SOL', 'XRP',
        'DOGE', 'ADA', 'AVAX', 'DOT', 'MATIC',
        'LINK', 'LTC', 'BCH', 'ETC', 'XLM',
        'ATOM', 'UNI', 'FIL', 'TRX', 'NEAR'
    }

    # 排除的稳定币
    EXCLUDE_STABLECOINS = {
        'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD'
    }

    # 排除的后缀（杠杆代币等）
    EXCLUDE_SUFFIXES = ['DOWN', 'UP', 'BEAR', 'BULL', '3L', '3S', '2L', '2S']

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    async def fetch_24h_tickers(self) -> List[TickerData]:
        """获取所有合约24h行情"""
        url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
        session = await self._get_session()

        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"API error: {resp.status}")
            data = await resp.json()

        tickers = []
        for item in data:
            symbol = item['symbol']
            # 只处理USDT本位永续合约
            if not symbol.endswith('USDT'):
                continue

            base_asset = symbol.replace('USDT', '')

            tickers.append(TickerData(
                symbol=symbol,
                base_asset=base_asset,
                price=float(item['lastPrice']),
                price_change_percent=float(item['priceChangePercent']),
                volume=float(item['volume']),
                quote_volume=float(item['quoteVolume'])
            ))

        return tickers

    def _is_excluded(self, base_asset: str) -> bool:
        """检查币种是否应被排除"""
        # 排除主流币
        if base_asset in self.EXCLUDE_MAJORS:
            return True
        # 排除稳定币
        if base_asset in self.EXCLUDE_STABLECOINS:
            return True
        # 排除杠杆代币
        if any(base_asset.endswith(suffix) for suffix in self.EXCLUDE_SUFFIXES):
            return True
        return False

    async def get_top_gainers(self, limit: int = 50) -> List[TickerData]:
        """
        获取涨幅榜 Top N（排除主流币和稳定币）

        Args:
            limit: 返回数量，默认50

        Returns:
            按涨幅降序排列的TickerData列表
        """
        tickers = await self.fetch_24h_tickers()

        # 过滤
        filtered = [t for t in tickers if not self._is_excluded(t.base_asset)]

        # 按涨幅降序排序
        sorted_tickers = sorted(
            filtered,
            key=lambda x: x.price_change_percent,
            reverse=True
        )

        return sorted_tickers[:limit]


async def main():
    """测试函数"""
    collector = BinanceMarketCollector()

    try:
        print("正在获取涨幅榜Top50...")
        top_gainers = await collector.get_top_gainers(50)

        print(f"\n{'排名':<4} {'交易对':<12} {'币种':<8} {'涨幅%':<10} {'价格':<15} {'成交额(USDT)':<15}")
        print("-" * 70)

        for i, ticker in enumerate(top_gainers, 1):
            print(f"{i:<4} {ticker.symbol:<12} {ticker.base_asset:<8} "
                  f"{ticker.price_change_percent:>8.2f}% "
                  f"{ticker.price:<15.6f} "
                  f"{ticker.quote_volume:>14,.0f}")

        print(f"\n共获取 {len(top_gainers)} 个币种")

        # 返回币种列表供后续使用
        return [t.base_asset for t in top_gainers]

    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
