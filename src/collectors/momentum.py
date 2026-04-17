"""
交易量和价格动能采集器
计算短期vs中期的比值，用于判断动能强度
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional, Dict
import aiohttp
from loguru import logger


@dataclass
class MomentumData:
    """动能数据"""
    symbol: str                    # 交易对，如 PEPEUSDT
    base_asset: str                # 币种，如 PEPE

    # 当前数据
    current_price: float           # 当前价格
    current_volume: float          # 当前5分钟成交量(USDT)

    # 短期数据 (5分钟级别)
    avg_volume_20: float           # 过去20个5分钟的平均成交量
    volume_ratio: float            # 成交量比值 = 当前 / 平均

    # 中期数据 (日级别)
    avg_price_5d: float            # 过去5天收盘价平均值
    price_ratio: float             # 价格比值 = 当前 / 平均

    # 综合评分
    momentum_score: float          # 动能评分

    success: bool                  # 是否获取成功
    error_msg: Optional[str] = None


class MomentumCollector:
    """动能数据采集器"""

    BASE_URL = "https://fapi.binance.com"

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

    async def _fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int
    ) -> Optional[List[dict]]:
        """
        获取K线数据

        Args:
            symbol: 交易对，如 PEPEUSDT
            interval: K线周期，如 5m, 1d
            limit: 获取数量

        Returns:
            K线数据列表，每个元素包含 [open_time, open, high, low, close, volume, ...]
        """
        url = f"{self.BASE_URL}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        session = await self._get_session()

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"K线请求失败 {symbol} {interval}: HTTP {resp.status}")
                    return None
                data = await resp.json()
                return data
        except Exception as e:
            logger.warning(f"K线请求异常 {symbol} {interval}: {e}")
            return None

    async def fetch_symbol_momentum(self, symbol: str) -> MomentumData:
        """
        获取单个交易对的动能数据

        Args:
            symbol: 交易对，如 PEPEUSDT

        Returns:
            MomentumData
        """
        base_asset = symbol.replace("USDT", "")

        # 并行获取5分钟K线和日K线
        klines_5m_task = self._fetch_klines(symbol, "5m", 21)  # 当前1根 + 过去20根
        klines_1d_task = self._fetch_klines(symbol, "1d", 6)   # 当前1根 + 过去5根

        klines_5m, klines_1d = await asyncio.gather(klines_5m_task, klines_1d_task)

        # 检查数据有效性
        if not klines_5m or len(klines_5m) < 21:
            return MomentumData(
                symbol=symbol,
                base_asset=base_asset,
                current_price=0,
                current_volume=0,
                avg_volume_20=0,
                volume_ratio=0,
                avg_price_5d=0,
                price_ratio=0,
                momentum_score=0,
                success=False,
                error_msg="5分钟K线数据不足"
            )

        if not klines_1d or len(klines_1d) < 6:
            return MomentumData(
                symbol=symbol,
                base_asset=base_asset,
                current_price=0,
                current_volume=0,
                avg_volume_20=0,
                volume_ratio=0,
                avg_price_5d=0,
                price_ratio=0,
                momentum_score=0,
                success=False,
                error_msg="日K线数据不足"
            )

        try:
            # K线格式: [open_time, open, high, low, close, volume, close_time,
            #           quote_volume, trades, taker_buy_volume, taker_buy_quote_volume, ignore]

            # 5分钟数据处理
            # 最后一根是当前未完成的K线，取倒数第二根作为最近完成的
            current_5m = klines_5m[-1]
            past_20_5m = klines_5m[:-1]  # 过去20根完成的K线

            current_price = float(current_5m[4])  # close price
            current_volume = float(current_5m[7])  # quote_volume (USDT成交额)

            # 计算过去20个5分钟的平均成交量
            volumes_20 = [float(k[7]) for k in past_20_5m]
            avg_volume_20 = sum(volumes_20) / len(volumes_20) if volumes_20 else 0

            # 计算成交量比值
            volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 0

            # 日K线数据处理
            # 最后一根是当天未完成的，取过去5天的收盘价
            past_5d = klines_1d[:-1]  # 过去5天完成的K线

            # 计算过去5天收盘价平均值
            closes_5d = [float(k[4]) for k in past_5d]
            avg_price_5d = sum(closes_5d) / len(closes_5d) if closes_5d else 0

            # 计算价格比值
            price_ratio = current_price / avg_price_5d if avg_price_5d > 0 else 0

            # 计算综合动能评分
            # volume_ratio > 1 表示放量，price_ratio > 1 表示价格高于均值
            # 评分 = 成交量比值 * 价格比值（双重确认）
            momentum_score = volume_ratio * price_ratio

            return MomentumData(
                symbol=symbol,
                base_asset=base_asset,
                current_price=current_price,
                current_volume=current_volume,
                avg_volume_20=avg_volume_20,
                volume_ratio=volume_ratio,
                avg_price_5d=avg_price_5d,
                price_ratio=price_ratio,
                momentum_score=momentum_score,
                success=True
            )

        except Exception as e:
            logger.warning(f"{symbol} 动能计算失败: {e}")
            return MomentumData(
                symbol=symbol,
                base_asset=base_asset,
                current_price=0,
                current_volume=0,
                avg_volume_20=0,
                volume_ratio=0,
                avg_price_5d=0,
                price_ratio=0,
                momentum_score=0,
                success=False,
                error_msg=str(e)
            )

    async def fetch_batch_momentum(
        self,
        symbols: List[str],
        concurrency: int = 10
    ) -> List[MomentumData]:
        """
        批量获取多个交易对的动能数据

        Args:
            symbols: 交易对列表
            concurrency: 并发数，默认10

        Returns:
            MomentumData 列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_with_semaphore(symbol: str) -> MomentumData:
            async with semaphore:
                return await self.fetch_symbol_momentum(symbol)

        tasks = [fetch_with_semaphore(s) for s in symbols]
        results = await asyncio.gather(*tasks)

        return list(results)


async def main():
    """测试函数"""
    # 测试几个交易对
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'PEPEUSDT', 'DOGEUSDT', 'SOLUSDT']

    collector = MomentumCollector()

    try:
        print("=" * 80)
        print("动能数据采集测试")
        print("=" * 80)
        print()

        results = await collector.fetch_batch_momentum(test_symbols)

        print(f"{'交易对':<12} {'当前价格':<15} {'成交量比':<10} {'价格比':<10} {'动能评分':<12} {'状态':<6}")
        print("-" * 75)

        for m in results:
            if m.success:
                print(f"{m.symbol:<12} {m.current_price:<15.6f} "
                      f"{m.volume_ratio:<10.2f} {m.price_ratio:<10.4f} "
                      f"{m.momentum_score:<12.4f} {'成功':<6}")
            else:
                print(f"{m.symbol:<12} {'N/A':<15} "
                      f"{'N/A':<10} {'N/A':<10} "
                      f"{'N/A':<12} {'失败':<6} - {m.error_msg}")

        print()
        print("=" * 80)
        print("指标说明:")
        print("  成交量比 = 当前5分钟成交量 / 过去20个5分钟平均成交量")
        print("  价格比   = 当前价格 / 过去5天收盘价平均值")
        print("  动能评分 = 成交量比 × 价格比")
        print("  成交量比 > 1 表示放量，价格比 > 1 表示高于均值")
        print("=" * 80)

    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
