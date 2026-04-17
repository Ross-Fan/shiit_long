# CLAUDE.md - 项目上下文

## 项目概述

山寨币合约做多策略的数据采集模块，用于 Binance Futures 交易。

**核心逻辑**: 热度 → OI资金验证 → 波动率入场 → 固定止损

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
├── shiit_long_main.py      # 主程序入口（定时采集）
├── test_collectors.py      # 测试脚本
├── requirements.txt
├── design.md               # 详细设计文档
├── instruction.md          # 原始需求说明
│
├── src/
│   ├── storage.py          # SQLite 数据存储层
│   └── collectors/
│       ├── binance_market.py   # 涨幅榜采集
│       ├── binance_square.py   # 广场热度爬虫
│       └── momentum.py         # 动能数据采集（成交量比/价格比）
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
   - 返回 `TickerData` 列表

2. **广场热度爬虫** (`src/collectors/binance_square.py`)
   - URL: `https://www.binance.com/en/square/hashtag/{TICKER}`
   - 顺序执行，3秒间隔
   - 抓取 views、discussing
   - 失败返回 -1，success=False

3. **动能数据采集** (`src/collectors/momentum.py`)
   - 成交量比 = 当前5分钟成交量 / 过去20个5分钟平均成交量
   - 价格比 = 当前价格 / 过去5天收盘价平均值
   - 动能评分 = 成交量比 × 价格比
   - API: `GET /fapi/v1/klines` (5m和1d周期)

4. **SQLite 数据存储** (`src/storage.py`)
   - `market_snapshots` 表：涨幅榜快照（含排名）
   - `square_hotness` 表：广场热度数据
   - `momentum_snapshots` 表：动能数据
   - `collection_logs` 表：采集任务日志

5. **定时采集主程序** (`shiit_long_main.py`)
   - 默认每 10 分钟执行一次
   - 三步采集：涨幅榜 → 广场热度 → 动能数据
   - 日志同时输出到控制台和文件
   - 优雅退出（Ctrl+C）

## 待实现功能

- OI（持仓量）数据采集
- 入场信号生成
- WebSocket 实时数据

## 关键类

```python
# 涨幅榜数据 (src/collectors/binance_market.py)
@dataclass
class TickerData:
    symbol: str              # PEPEUSDT
    base_asset: str          # PEPE
    price: float
    price_change_percent: float
    volume: float
    quote_volume: float

# 广场热度 (src/collectors/binance_square.py)
@dataclass
class SquareHotness:
    symbol: str
    view_count: int          # -1 表示失败
    discuss_count: int
    hotness_score: float
    success: bool

# 动能数据 (src/collectors/momentum.py)
@dataclass
class MomentumData:
    symbol: str              # PEPEUSDT
    base_asset: str          # PEPE
    current_price: float
    current_volume: float    # 当前5分钟成交量
    avg_volume_20: float     # 过去20个5分钟平均成交量
    volume_ratio: float      # 成交量比值
    avg_price_5d: float      # 过去5天收盘价平均
    price_ratio: float       # 价格比值
    momentum_score: float    # 动能评分 = volume_ratio * price_ratio
    success: bool
```

## 数据库表结构

```sql
-- 市场快照
market_snapshots (
    id, snapshot_time, symbol, base_asset, price,
    price_change_percent, volume, quote_volume, rank
)

-- 广场热度
square_hotness (
    id, snapshot_time, symbol, view_count,
    discuss_count, hotness_score, success
)

-- 动能数据
momentum_snapshots (
    id, snapshot_time, symbol, base_asset, current_price,
    current_volume, avg_volume_20, volume_ratio,
    avg_price_5d, price_ratio, momentum_score, success
)

-- 采集日志
collection_logs (
    id, snapshot_time, market_count, square_count, square_success,
    momentum_count, momentum_success, duration_seconds, status
)
```

## 常用命令

```bash
# 启动定时服务（每10分钟）
python shiit_long_main.py

# 自定义间隔（每30分钟）
python shiit_long_main.py --interval=30

# 单次执行
python shiit_long_main.py --once

# 自定义热度抓取数量
python shiit_long_main.py --square-limit=10

# 后台运行（日志自动写入文件）
nohup python3 shiit_long_main.py > /dev/null 2>&1 &

# 查看日志
tail -f logs/shiit_long.log

# 测试各采集器
python -m src.collectors.binance_market
python -m src.collectors.binance_square
python -m src.collectors.momentum
```

## 配置参数

主程序配置在 `shiit_long_main.py` 中：

```python
CONFIG = {
    "top_gainers_limit": 60,       # 涨幅榜数量
    "square_fetch_limit": 60,      # 广场热度抓取数量
    "square_delay": 3.0,           # 广场抓取间隔（秒）
    "momentum_concurrency": 10,    # 动能数据并发数
    "schedule_interval_minutes": 10,  # 定时间隔（分钟）
    "db_path": "data/shiit_long.db",
    "log_path": "logs/shiit_long.log",
}
```

## 动能指标说明

- **成交量比 > 1**: 表示放量，当前成交活跃
- **价格比 > 1**: 表示价格高于近期均值，处于上涨趋势
- **动能评分**: 综合指标，越高表示动能越强

## 设计文档

详细设计见 `design.md`，包含：
- 数据库表结构
- WebSocket 流订阅策略
- 波动率计算公式
- 完整数据流程图
