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
│       └── binance_square.py   # 广场热度爬虫
│
├── data/
│   └── shiit_long.db       # SQLite 数据库
└── logs/                   # 日志目录
```

## 已实现功能

1. **涨幅榜 Top50** (`src/collectors/binance_market.py`)
   - API: `GET /fapi/v1/ticker/24hr`
   - 过滤主流币/稳定币/杠杆代币
   - 返回 `TickerData` 列表

2. **广场热度爬虫** (`src/collectors/binance_square.py`)
   - URL: `https://www.binance.com/en/square/hashtag/{TICKER}`
   - 顺序执行，3秒间隔
   - 抓取 views、discussing
   - 失败返回 -1，success=False

3. **SQLite 数据存储** (`src/storage.py`)
   - `market_snapshots` 表：涨幅榜快照（含排名）
   - `square_hotness` 表：广场热度数据
   - `collection_logs` 表：采集任务日志
   - 提供历史查询、统计接口

4. **定时采集主程序** (`shiit_long_main.py`)
   - 默认每 15 分钟执行一次
   - 自动保存数据到 SQLite
   - 支持命令行参数配置
   - 优雅退出（Ctrl+C）

## 待实现功能

- WebSocket 客户端 (Funding Rate / K线)
- 波动率计算器
- OI 数据采集
- 入场信号生成

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

# 数据库管理 (src/storage.py)
class Database:
    def save_market_snapshots(tickers, snapshot_time)
    def save_square_hotness(hotness_list, snapshot_time)
    def log_collection(...)
    def get_latest_market_snapshot() -> List[dict]
    def get_latest_square_hotness() -> List[dict]
    def get_symbol_history(symbol, hours) -> dict
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

-- 采集日志
collection_logs (
    id, snapshot_time, market_count, square_count,
    square_success, duration_seconds, status, error_message
)
```

## 常用命令

```bash
# 启动定时服务（每15分钟）
python shiit_long_main.py

# 自定义间隔（每30分钟）
python shiit_long_main.py --interval=30

# 单次执行
python shiit_long_main.py --once

# 自定义热度抓取数量
python shiit_long_main.py --square-limit=10

# 后台运行
nohup python shiit_long_main.py > logs/shiit_long.log 2>&1 &

# 测试涨幅榜
python -m src.collectors.binance_market

# 测试广场爬虫
python -m src.collectors.binance_square

# 完整测试
python test_collectors.py
```

## 配置参数

主程序配置在 `shiit_long_main.py` 中：

```python
CONFIG = {
    "top_gainers_limit": 50,       # 涨幅榜数量
    "square_fetch_limit": 20,      # 广场热度抓取数量
    "square_delay": 3.0,           # 广场抓取间隔（秒）
    "schedule_interval_minutes": 15,  # 定时间隔（分钟）
    "db_path": "data/shiit_long.db",
}
```

## 设计文档

详细设计见 `design.md`，包含：
- 数据库表结构
- WebSocket 流订阅策略
- 波动率计算公式
- 完整数据流程图
