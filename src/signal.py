"""
入场信号生成器
多条件过滤，综合热度、成交量、价格等指标判断入场时机
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from loguru import logger


@dataclass
class SignalConfig:
    """信号过滤条件配置"""
    # 涨幅榜排名条件
    max_rank: int = 30                    # 排名 <= 30

    # 动能条件
    min_volume_ratio: float = 1.5         # 成交量比 >= 1.5 (放量)
    min_price_ratio: float = 1.0          # 价格比 >= 1.0 (站上均价)

    # 热度条件
    min_discuss_count: int = 1000         # 最小讨论数
    min_view_count: int = 100000          # 最小浏览量

    # 涨幅条件
    min_price_change: float = 5.0         # 最小涨幅 5%
    max_price_change: float = 100.0       # 最大涨幅 100% (避免追高)


@dataclass
class EntrySignal:
    """入场信号"""
    symbol: str                           # 交易对 PEPEUSDT
    base_asset: str                       # 币种 PEPE
    signal_time: datetime                 # 信号时间

    # 市场数据
    price: float                          # 当前价格
    price_change_percent: float           # 24h涨幅
    rank: int                             # 涨幅榜排名

    # 动能数据
    volume_ratio: float                   # 成交量比
    price_ratio: float                    # 价格比
    momentum_score: float                 # 动能评分

    # 热度数据
    view_count: int                       # 浏览量
    discuss_count: int                    # 讨论数

    # 信号强度
    signal_strength: str                  # 强/中/弱

    # 满足的条件
    conditions_met: List[str] = field(default_factory=list)


class SignalGenerator:
    """入场信号生成器"""

    def __init__(self, config: Optional[SignalConfig] = None):
        self.config = config or SignalConfig()

    def generate_signals(
        self,
        market_data: List[Dict],
        momentum_data: List[Dict],
        hotness_data: List[Dict]
    ) -> List[EntrySignal]:
        """
        生成入场信号

        Args:
            market_data: 市场数据列表 (从 market_snapshots 表)
            momentum_data: 动能数据列表 (从 momentum_snapshots 表)
            hotness_data: 热度数据列表 (从 square_hotness 表)

        Returns:
            满足条件的入场信号列表
        """
        # 构建索引
        momentum_map = {m['symbol']: m for m in momentum_data if m.get('success', 1)}
        hotness_map = {h['symbol']: h for h in hotness_data if h.get('success', 1)}

        signals = []

        for market in market_data:
            symbol = market['symbol']
            base_asset = market['base_asset']
            rank = market['rank']

            # 获取关联数据
            momentum = momentum_map.get(symbol, {})
            hotness = hotness_map.get(base_asset, {})

            # 检查各条件
            conditions_met = []
            conditions_failed = []

            # 1. 排名条件
            if rank <= self.config.max_rank:
                conditions_met.append(f"排名#{rank}")
            else:
                conditions_failed.append("排名过低")
                continue  # 排名是硬性条件

            # 2. 涨幅条件
            price_change = market['price_change_percent']
            if self.config.min_price_change <= price_change <= self.config.max_price_change:
                conditions_met.append(f"涨幅{price_change:.1f}%")
            else:
                if price_change < self.config.min_price_change:
                    conditions_failed.append("涨幅不足")
                else:
                    conditions_failed.append("涨幅过高")
                continue  # 涨幅也是硬性条件

            # 3. 成交量比条件
            volume_ratio = momentum.get('volume_ratio', 0)
            if volume_ratio >= self.config.min_volume_ratio:
                conditions_met.append(f"放量{volume_ratio:.1f}x")
            else:
                conditions_failed.append(f"成交量不足({volume_ratio:.1f}x)")
                continue

            # 4. 价格比条件
            price_ratio = momentum.get('price_ratio', 0)
            if price_ratio >= self.config.min_price_ratio:
                conditions_met.append(f"突破均价{price_ratio:.2f}x")
            else:
                conditions_failed.append(f"未突破均价({price_ratio:.2f}x)")
                continue

            # 5. 热度条件 (可选，有数据才检查)
            discuss_count = hotness.get('discuss_count', 0)
            view_count = hotness.get('view_count', 0)

            hotness_ok = True
            if discuss_count > 0 or view_count > 0:
                if discuss_count >= self.config.min_discuss_count:
                    conditions_met.append(f"讨论{discuss_count:,}")
                elif discuss_count > 0:
                    hotness_ok = False
                    conditions_failed.append(f"讨论不足({discuss_count:,})")

                if view_count >= self.config.min_view_count:
                    conditions_met.append(f"浏览{view_count:,}")

            # 如果热度数据充足但不满足条件，跳过
            if discuss_count > 0 and not hotness_ok:
                continue

            # 所有条件通过，生成信号
            signal_strength = self._calc_signal_strength(
                volume_ratio, price_ratio, discuss_count, rank
            )

            signal = EntrySignal(
                symbol=symbol,
                base_asset=base_asset,
                signal_time=datetime.now(),
                price=market['price'],
                price_change_percent=price_change,
                rank=rank,
                volume_ratio=volume_ratio,
                price_ratio=price_ratio,
                momentum_score=momentum.get('momentum_score', 0),
                view_count=view_count,
                discuss_count=discuss_count,
                signal_strength=signal_strength,
                conditions_met=conditions_met
            )

            signals.append(signal)

        # 按动能评分排序
        signals.sort(key=lambda x: x.momentum_score, reverse=True)

        return signals

    def _calc_signal_strength(
        self,
        volume_ratio: float,
        price_ratio: float,
        discuss_count: int,
        rank: int
    ) -> str:
        """计算信号强度"""
        score = 0

        # 成交量得分
        if volume_ratio >= 3.0:
            score += 3
        elif volume_ratio >= 2.0:
            score += 2
        elif volume_ratio >= 1.5:
            score += 1

        # 价格得分
        if price_ratio >= 1.2:
            score += 2
        elif price_ratio >= 1.1:
            score += 1

        # 热度得分
        if discuss_count >= 10000:
            score += 2
        elif discuss_count >= 5000:
            score += 1

        # 排名得分
        if rank <= 10:
            score += 2
        elif rank <= 20:
            score += 1

        if score >= 6:
            return "强"
        elif score >= 3:
            return "中"
        else:
            return "弱"

    def format_signals(self, signals: List[EntrySignal]) -> str:
        """格式化信号输出"""
        if not signals:
            return "无入场信号"

        lines = [
            f"发现 {len(signals)} 个入场信号:",
            "-" * 70,
            f"{'币种':<10} {'涨幅':<8} {'排名':<6} {'放量':<8} {'价格比':<8} {'强度':<6} {'条件'}",
            "-" * 70
        ]

        for s in signals:
            conditions = ", ".join(s.conditions_met[:3])  # 只显示前3个条件
            lines.append(
                f"{s.base_asset:<10} "
                f"{s.price_change_percent:>6.1f}% "
                f"#{s.rank:<5} "
                f"{s.volume_ratio:>6.1f}x "
                f"{s.price_ratio:>6.2f}x "
                f"{s.signal_strength:<6} "
                f"{conditions}"
            )

        return "\n".join(lines)


def generate_signals_from_db(db, config: Optional[SignalConfig] = None) -> List[EntrySignal]:
    """
    从数据库生成入场信号

    Args:
        db: Database 实例
        config: 信号配置

    Returns:
        入场信号列表
    """
    # 获取最新数据
    market_data = db.get_latest_market_snapshot()
    momentum_data = db.get_latest_momentum()
    hotness_data = db.get_latest_square_hotness()

    if not market_data:
        logger.warning("无市场数据")
        return []

    logger.info(f"加载数据: 市场={len(market_data)}, 动能={len(momentum_data)}, 热度={len(hotness_data)}")

    # 生成信号
    generator = SignalGenerator(config)
    signals = generator.generate_signals(market_data, momentum_data, hotness_data)

    return signals


# 测试代码
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')

    from src.storage import Database

    db = Database("data/shiit_long.db")

    # 使用默认配置
    config = SignalConfig(
        max_rank=30,
        min_volume_ratio=1.0,      # 放宽条件测试
        min_price_ratio=0.9,
        min_discuss_count=0,
        min_view_count=0,
        min_price_change=3.0,
        max_price_change=200.0
    )

    signals = generate_signals_from_db(db, config)

    generator = SignalGenerator(config)
    print()
    print("=" * 70)
    print("入场信号扫描")
    print("=" * 70)
    print()
    print(generator.format_signals(signals))
    print()
    print("=" * 70)
    print(f"过滤条件: 排名≤{config.max_rank}, 放量≥{config.min_volume_ratio}x, "
          f"价格比≥{config.min_price_ratio}, 涨幅{config.min_price_change}%-{config.max_price_change}%")
    print("=" * 70)
