# CLAUDE.md - 项目上下文

## 项目概述

山寨币合约做多策略的数据采集模块，用于 Binance Futures 交易。

**核心逻辑**: 热度 → 动能验证 → 入场信号 → 固定止损

## 技术栈

- Python 3.9+
- aiohttp (HTTP客户端)
- playwright (广场爬虫)
- SQLite (数据存储)
- APScheduler (定时任务)
- loguru (日志系统)

## 项目结构

```
shiit_long/
├── shiit_long_main.py      # 主程序入口（定时采集+信号生成）
├── test_collectors.py      # 测试脚本
├── requirements.txt
├── design.md               # 详细设计文档
├── instruction.md          # 原始需求说明
│
├── src/
│   ├── storage.py          # SQLite 数据存储层
│   ├── signal.py           # 入场信号生成器
│   └── collectors/
│       ├── binance_market.py   # 涨幅榜采集
│       ├── binance_square.py   # 广场热度爬虫
│       └── momentum.py         # 动能数据采集
│
├── data/
│   └── shiit_long.db       # SQLite 数据库
└── logs/
    └── shiit_long.log      # 日志文件
```

## 已实现功能

1. **涨幅榜 Top60** (`src/collectors/binance_market.py`)
   - API: `GET /fapi/v1/ticker/24hr`
   - 过滤主流币/稳定币/杠杆代币

2. **广场热度爬虫** (`src/collectors/binance_square.py`)
   - URL: `https://www.binance.com/en/square/hashtag/{TICKER}`
   - 顺序执行，3秒间隔

3. **动能数据采集** (`src/collectors/momentum.py`)
   - 成交量比 = 当前5分钟成交量 / 过去20个5分钟平均
   - 价格比 = 当前价格 / 过去5天收盘价平均

4. **入场信号生成** (`src/signal.py`)
   - 多条件过滤：排名、涨幅、成交量比、价格比
   - 信号强度评估：强/中/弱
   - 自动保存到数据库

5. **定时采集主程序** (`shiit_long_main.py`)
   - 4步流程：涨幅榜 → 广场热度 → 动能数据 → 入场信号
   - 日志同时输出到控制台和文件

## 入场信号配置

```python
# shiit_long_main.py 中的 SIGNAL_CONFIG
SignalConfig(
    max_rank=30,                # 排名 <= 30
    min_volume_ratio=0.5,       # 成交量比 >= 0.5
    min_price_ratio=1.0,        # 价格比 >= 1.0 (站上5日均价)
    min_discuss_count=0,        # 讨论数 (暂不限制)
    min_view_count=0,           # 浏览量 (暂不限制)
    min_price_change=5.0,       # 最小涨幅 5%
    max_price_change=300.0,     # 最大涨幅 300%
)
```

**信号触发条件（全部满足）：**
- 涨幅榜排名 ≤ 30
- 24h涨幅在 5%-300% 之间
- 成交量比 ≥ 0.5（当前vs过去20个5分钟均值）
- 价格比 ≥ 1.0（站上5日均价）

## 数据库表结构

```sql
-- 市场快照
market_snapshots (symbol, base_asset, price, price_change_percent, rank)

-- 广场热度
square_hotness (symbol, view_count, discuss_count, hotness_score)

-- 动能数据
momentum_snapshots (symbol, volume_ratio, price_ratio, momentum_score)

-- 入场信号
entry_signals (symbol, price, rank, volume_ratio, price_ratio, signal_strength)
```

## 常用命令

```bash
# 启动定时服务
python shiit_long_main.py

# 单次执行
python shiit_long_main.py --once

# 后台运行
nohup python3 shiit_long_main.py > /dev/null 2>&1 &

# 查看日志
tail -f logs/shiit_long.log

# 测试信号生成
python -m src.signal
```

## 关键类

```python
# 入场信号 (src/signal.py)
@dataclass
class EntrySignal:
    symbol: str              # PEPEUSDT
    base_asset: str          # PEPE
    price: float
    price_change_percent: float
    rank: int
    volume_ratio: float      # 成交量比
    price_ratio: float       # 价格比
    signal_strength: str     # 强/中/弱
    conditions_met: List[str]  # 满足的条件

# 信号生成器 (src/signal.py)
class SignalGenerator:
    def generate_signals(market, momentum, hotness) -> List[EntrySignal]
```

## 待实现功能

- OI（持仓量）数据采集
- WebSocket 实时数据
- 交易执行模块

## 信号强度说明

| 强度 | 得分 | 特征 |
|------|------|------|
| 强 | ≥6 | 高放量(3x+)、突破均价(1.2x+)、高热度、Top10排名 |
| 中 | 3-5 | 放量(1.5-3x)、突破均价、有热度 |
| 弱 | <3 | 刚满足基本条件 |
