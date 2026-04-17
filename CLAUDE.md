# CLAUDE.md - 项目上下文

## 项目概述

山寨币合约做多策略的数据采集模块，用于 Binance Futures 交易。

**核心逻辑**: 热度 → OI资金验证 → 波动率入场 → 固定止损

## 技术栈

- Python 3.9+
- aiohttp (HTTP客户端)
- playwright (广场爬虫)
- SQLite (数据存储，待实现)

## 项目结构

```
shiit_long/
├── src/collectors/
│   ├── binance_market.py   # 涨幅榜采集 (Binance Futures API)
│   └── binance_square.py   # 广场热度爬虫 (playwright)
├── design.md               # 详细设计文档
├── instruction.md          # 原始需求说明
├── test_collectors.py      # 测试脚本
└── requirements.txt
```

## 已实现功能

1. **涨幅榜 Top50** (`binance_market.py`)
   - API: `GET /fapi/v1/ticker/24hr`
   - 过滤主流币/稳定币/杠杆代币
   - 返回 `TickerData` 列表

2. **广场热度爬虫** (`binance_square.py`)
   - URL: `https://www.binance.com/en/square/hashtag/{TICKER}`
   - 顺序执行，3秒间隔
   - 抓取 views、discussing
   - 失败返回 -1，success=False

## 待实现功能

- WebSocket 客户端 (Funding Rate / K线)
- 波动率计算器
- OI 数据采集
- SQLite 存储
- 定时调度

## 关键类

```python
# 涨幅榜数据
@dataclass
class TickerData:
    symbol: str              # PEPEUSDT
    base_asset: str          # PEPE
    price: float
    price_change_percent: float
    volume: float
    quote_volume: float

# 广场热度
@dataclass
class SquareHotness:
    symbol: str
    view_count: int          # -1 表示失败
    discuss_count: int
    hotness_score: float
    success: bool
```

## 常用命令

```bash
# 测试涨幅榜
python -m src.collectors.binance_market

# 测试广场爬虫
python -m src.collectors.binance_square

# 完整测试
python test_collectors.py
```

## 设计文档

详细设计见 `design.md`，包含：
- 数据库表结构
- WebSocket 流订阅策略
- 波动率计算公式
- 完整数据流程图
