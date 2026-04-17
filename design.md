# 山寨币合约数据采集模块设计方案

## 1. 技术选型

| 项目 | 选择 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | 生态丰富，有现成的交易库 |
| 数据库 | SQLite | 轻量级，无需额外部署 |
| HTTP客户端 | aiohttp/httpx | 异步，高效并发 |
| WebSocket | websockets/aiohttp | 实时数据推送（Funding Rate等） |
| 爬虫 | playwright | 处理JS渲染的现代方案 |
| 日志 | loguru | 简洁强大的日志库 |
| 定时 | apscheduler | 灵活的任务调度 |

## 2. 项目结构

```
shiit_long/
├── .env                          # API密钥等敏感信息
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git忽略规则
├── requirements.txt              # Python依赖
├── main.py                       # 程序入口
│
├── config/
│   └── config.yaml               # 配置文件
│
├── data/
│   └── shiit_long.db             # SQLite数据库
│
├── logs/
│   ├── shiit_long.log            # 主日志
│   ├── signals.log               # 信号日志
│   └── errors.log                # 错误日志
│
├── src/
│   ├── __init__.py
│   ├── config.py                 # 配置加载器
│   ├── logger.py                 # 日志系统
│   ├── models.py                 # 数据模型
│   ├── storage.py                # SQLite存储层
│   ├── utils.py                  # 工具函数
│   │
│   ├── collectors/               # 数据采集模块
│   │   ├── __init__.py
│   │   ├── base.py               # 采集器基类
│   │   ├── binance_market.py     # Binance行情数据 (REST)
│   │   ├── binance_futures.py    # 合约OI数据 (REST)
│   │   ├── binance_ws.py         # WebSocket客户端 (Mark Price/Funding Rate/K线)
│   │   └── binance_square.py     # 币安广场爬虫
│   │
│   ├── analyzers/                # 分析模块
│   │   ├── __init__.py
│   │   └── volatility.py         # 波动率计算器
│   │
│   └── filters/                  # 过滤模块
│       ├── __init__.py
│       └── coin_filter.py        # 币种过滤器
│
└── tests/                        # 测试目录（预留）
```

## 3. 数据库表结构设计

### 3.1 币种基础信息表 (symbols)

```sql
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,           -- 交易对，如 BTCUSDT
    base_asset TEXT NOT NULL,          -- 基础资产，如 BTC
    quote_asset TEXT NOT NULL,         -- 计价资产，如 USDT
    status TEXT DEFAULT 'TRADING',     -- 交易状态
    contract_type TEXT,                -- 合约类型：PERPETUAL
    first_seen REAL NOT NULL,          -- 首次发现时间戳
    last_update REAL NOT NULL,         -- 最后更新时间戳
    is_excluded INTEGER DEFAULT 0      -- 是否被排除（1=是）
);
```

### 3.2 行情快照表 (market_snapshots)

```sql
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp REAL NOT NULL,           -- Unix时间戳
    price REAL DEFAULT 0,              -- 当前价格
    price_change_24h REAL DEFAULT 0,   -- 24h涨跌幅 (%)
    volume_24h REAL DEFAULT 0,         -- 24h成交量
    quote_volume_24h REAL DEFAULT 0,   -- 24h成交额 (USDT)
    high_24h REAL DEFAULT 0,           -- 24h最高价
    low_24h REAL DEFAULT 0,            -- 24h最低价
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_symbol_time
    ON market_snapshots(symbol, timestamp);
```

### 3.3 合约数据表 (futures_snapshots)

```sql
CREATE TABLE IF NOT EXISTS futures_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp REAL NOT NULL,
    open_interest REAL DEFAULT 0,      -- 持仓量（合约数量）
    open_interest_value REAL DEFAULT 0,-- 持仓价值（USDT）
    funding_rate REAL DEFAULT 0,       -- 资金费率
    mark_price REAL DEFAULT 0,         -- 标记价格
    index_price REAL DEFAULT 0,        -- 指数价格
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_futures_symbol_time
    ON futures_snapshots(symbol, timestamp);
```

### 3.4 币安广场热度表 (square_hotness)

```sql
CREATE TABLE IF NOT EXISTS square_hotness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,              -- 币种代码（如 PEPE）
    timestamp REAL NOT NULL,           -- 采集时间戳
    view_count INTEGER DEFAULT 0,      -- 话题总浏览量
    discuss_count INTEGER DEFAULT 0,   -- 话题总讨论数（帖子数）
    hot_posts_engagement INTEGER DEFAULT 0,  -- 热门帖子互动数加权
    hotness_score REAL DEFAULT 0,      -- 综合热度评分
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_square_symbol_time
    ON square_hotness(symbol, timestamp);
```

### 3.5 K线数据表 (klines)

```sql
CREATE TABLE IF NOT EXISTS klines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,            -- K线周期: 5m, 1h
    open_time REAL NOT NULL,           -- K线开盘时间
    open REAL NOT NULL,                -- 开盘价
    high REAL NOT NULL,                -- 最高价
    low REAL NOT NULL,                 -- 最低价
    close REAL NOT NULL,               -- 收盘价
    volume REAL NOT NULL,              -- 成交量
    close_time REAL NOT NULL,          -- K线收盘时间
    quote_volume REAL DEFAULT 0,       -- 成交额
    trades INTEGER DEFAULT 0,          -- 成交笔数
    is_closed INTEGER DEFAULT 0,       -- K线是否已收盘
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_time
    ON klines(symbol, interval, open_time);
```

### 3.6 聚合分析表 (analysis_results)

```sql
CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp REAL NOT NULL,

    -- 行情数据
    price REAL DEFAULT 0,
    price_change_24h REAL DEFAULT 0,
    volume_24h REAL DEFAULT 0,

    -- 合约数据
    open_interest REAL DEFAULT 0,
    oi_change_1h REAL DEFAULT 0,       -- 1小时OI变化率 (%)
    funding_rate REAL DEFAULT 0,

    -- 波动率数据
    volatility_5m REAL DEFAULT 0,      -- 5分钟振幅 (%)
    volatility_1h_avg REAL DEFAULT 0,  -- 1小时平均振幅 (%)
    volatility_ratio REAL DEFAULT 0,   -- 波动比 = 5m振幅 / 1h均振幅
    volume_5m REAL DEFAULT 0,          -- 5分钟成交量
    volume_1h_avg REAL DEFAULT 0,      -- 1小时平均成交量
    volume_ratio REAL DEFAULT 0,       -- 量比 = 5m成交量 / 1h均成交量

    -- 广场热度
    hotness_score REAL DEFAULT 0,
    hotness_rank INTEGER DEFAULT 0,    -- 热度排名

    -- 涨幅榜排名
    gainers_rank INTEGER DEFAULT 0,    -- 24h涨幅榜排名

    -- 综合评分
    total_score REAL DEFAULT 0,

    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_analysis_symbol_time
    ON analysis_results(symbol, timestamp);
```

## 4. 各数据源采集方案

### 4.1 Binance 行情数据 (binance_market.py)

**API端点:**

| 用途 | 端点 | Weight |
|------|------|--------|
| 24h Ticker | `GET /fapi/v1/ticker/24hr` | 40 |

**核心逻辑:**

```python
class BinanceMarketCollector:
    BASE_URL = "https://fapi.binance.com"

    async def fetch_24h_tickers(self) -> List[TickerData]:
        """获取所有合约24h行情"""
        url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return [self._parse_ticker(t) for t in data]

    async def get_top_gainers(self, limit: int = 100) -> List[TickerData]:
        """获取涨幅榜 Top N"""
        tickers = await self.fetch_24h_tickers()
        # 过滤USDT本位合约
        usdt_tickers = [t for t in tickers if t.symbol.endswith('USDT')]
        # 按涨幅排序
        sorted_tickers = sorted(usdt_tickers,
                                key=lambda x: x.price_change_percent,
                                reverse=True)
        return sorted_tickers[:limit]
```

### 4.2 合约数据采集方案

采用 **REST + WebSocket 混合架构**：

| 数据 | 获取方式 | 说明 |
|------|----------|------|
| Funding Rate | **WebSocket** | `!markPrice@arr@1s` 全市场推送，每秒更新 |
| Mark Price | **WebSocket** | 同上，包含在 Mark Price Stream |
| Index Price | **WebSocket** | 同上 |
| 5分钟K线 | **WebSocket** | `<symbol>@kline_5m` Top100币种订阅，用于波动率计算 |
| Open Interest | REST API | 无 WebSocket 支持，需轮询 |
| 历史 OI | REST API | 用于计算 OI 变化率 |
| 历史K线 | REST API | 初始化时获取过去1小时数据 |

#### 4.2.1 WebSocket 数据流 (binance_ws.py)

**连接信息:**
- Base URL: `wss://fstream.binance.com`
- 全市场 Mark Price: `wss://fstream.binance.com/ws/!markPrice@arr@1s`
- 组合流订阅: `wss://fstream.binance.com/stream?streams=<stream1>/<stream2>/...`

**WebSocket 流订阅策略:**

| 流类型 | 订阅方式 | 数量 | 说明 |
|--------|----------|------|------|
| Mark Price | `!markPrice@arr@1s` | 1个流 | 全市场推送，包含Funding Rate |
| 5分钟K线 | `<symbol>@kline_5m` | 100个流 | Top100币种各订阅一个 |

总计约101个流，远低于1024上限。

**Mark Price Stream 数据结构:**

```json
{
  "e": "markPriceUpdate",
  "s": "BTCUSDT",
  "p": "11794.15000000",      // 标记价格
  "r": "0.00038167",          // 资金费率
  "T": 1596608400000          // 下次资金时间
}
```

**K线 Stream 数据结构:**

```json
{
  "e": "kline",
  "s": "BTCUSDT",
  "k": {
    "t": 1638747660000,       // K线开盘时间
    "T": 1638747719999,       // K线收盘时间
    "s": "BTCUSDT",
    "i": "5m",                // K线周期
    "o": "49000.00",          // 开盘价
    "c": "49100.00",          // 收盘价
    "h": "49200.00",          // 最高价
    "l": "48900.00",          // 最低价
    "v": "1000",              // 成交量
    "q": "49000000",          // 成交额
    "x": false                // K线是否已收盘
  }
}
```

**动态订阅管理:**

由于涨幅榜Top100会变化，需要动态管理K线订阅：
1. 每次获取新的Top100列表后，对比当前订阅
2. 取消不在新列表中的币种订阅
3. 添加新进入Top100的币种订阅
4. 使用WebSocket的 SUBSCRIBE/UNSUBSCRIBE 方法动态调整

#### 4.2.2 Open Interest (REST API - binance_futures.py)

OI 数据无 WebSocket 支持，仍需通过 REST API 获取：

**API端点:**

| 用途 | 端点 | Weight |
|------|------|--------|
| 当前OI | `GET /fapi/v1/openInterest` | 1 |
| 历史OI | `GET /futures/data/openInterestHist` | 1 |
| 历史K线 | `GET /fapi/v1/klines` | 5 |

历史K线接口用于初始化时获取过去1小时的K线数据，之后通过WebSocket实时更新。

### 4.3 波动率计算方案 (volatility.py)

基于 **价格 + 成交量** 双维度，采用 **5分钟短期 vs 1小时长期** 对比：

#### 4.3.1 计算指标

| 指标 | 计算公式 | 说明 |
|------|----------|------|
| 5分钟振幅 | `(High - Low) / Open × 100%` | 当前K线的价格波动幅度 |
| 1小时均振幅 | `过去12根5分钟K线振幅的均值` | 长期波动基准 |
| 波动比 | `5分钟振幅 / 1小时均振幅` | >1表示短期波动超过长期平均 |
| 5分钟成交量 | 当前K线成交量 | 短期量能 |
| 1小时均成交量 | `过去12根5分钟K线成交量均值` | 长期量能基准 |
| 量比 | `5分钟成交量 / 1小时均成交量` | >1表示放量 |

#### 4.3.2 数据来源

- **实时数据**: WebSocket `<symbol>@kline_5m` 推送（每250ms更新）
- **历史数据**: 内存中维护每个币种最近12根已完成K线的滑动窗口
- **初始化**: 启动时通过REST API获取每个币种过去1小时K线

#### 4.3.3 波动触发条件示例

```
波动比 > 1.5 且 量比 > 2.0
```

表示：当前5分钟的价格波动超过过去1小时平均的1.5倍，且成交量超过2倍。

### 4.4 币安广场热度采集 (binance_square.py)

**采集方式**: 按币种查询 hashtag 页面（无需登录）

**URL格式**: `https://www.binance.com/en/square/hashtag/{TICKER}`

例如：`https://www.binance.com/en/square/hashtag/PEPE`

#### 4.4.1 可抓取数据

| 数据 | 位置 | 说明 |
|------|------|------|
| view | 页面顶部 | 该话题总浏览量 |
| discuss | 页面顶部 | 该话题总讨论数（帖子数） |
| hot 帖子 | Hot板块 | 热门帖子列表 |
| latest 帖子 | Latest板块 | 最新帖子列表 |
| 帖子互动数 | 每个帖子 | 点赞/评论/分享数 |

#### 4.4.2 采集流程

1. **输入**: 从涨幅榜获取的 Top100 币种列表
2. **遍历**: 访问每个币种的 hashtag 页面
3. **抓取**: 提取 view、discuss、hot帖子互动数据
4. **计算**: 生成热度分数

#### 4.4.3 热度计算公式

```
热度分数 = view × 0.001 + discuss × 1.0 + hot帖子互动加权

帖子互动加权 = Σ(点赞×1 + 评论×2 + 分享×3)  // 取hot板块前10条
```

#### 4.4.4 爬虫注意事项

1. **无需登录**: hashtag 页面公开可访问
2. **频率控制**: 100个币种，建议间隔0.5-1秒，总耗时约1-2分钟
3. **并发控制**: 可适度并发（5-10个），但需注意限流
4. **User-Agent**: 添加随机浏览器UA
5. **CSS选择器**: 需要根据实际页面结构调整，可能随版本变化
6. **降级策略**: 如抓取失败，该币种热度记为0，不影响其他指标

## 5. 币种过滤器

```python
class CoinFilter:
    """币种过滤器"""

    # 排除的主流币
    EXCLUDE_MAJORS = {
        'BTC', 'ETH', 'BNB', 'SOL', 'XRP',
        'DOGE', 'ADA', 'AVAX', 'DOT', 'MATIC'
    }

    # 排除的稳定币
    EXCLUDE_STABLECOINS = {
        'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'
    }

    # 排除的后缀（杠杆代币、股票代币等）
    EXCLUDE_SUFFIXES = ['DOWN', 'UP', 'BEAR', 'BULL', '3L', '3S']

    def filter(self, symbols: List[str]) -> List[str]:
        """过滤币种"""
        result = []
        for symbol in symbols:
            base = symbol.replace('USDT', '')

            if base in self.EXCLUDE_MAJORS:
                continue
            if base in self.EXCLUDE_STABLECOINS:
                continue
            if any(base.endswith(suffix) for suffix in self.EXCLUDE_SUFFIXES):
                continue

            result.append(symbol)

        return result
```

## 6. 配置文件 (config/config.yaml)

```yaml
# 采集器配置
collector:
  interval_minutes: 3           # 轮询间隔
  top_gainers_limit: 100        # 涨幅榜取前N
  top_hotness_limit: 30         # 广场热度取前N

# 过滤配置
filter:
  exclude_majors:
    - BTC
    - ETH
    - BNB
    - SOL
    - XRP
    - DOGE
    - ADA
    - AVAX
    - DOT
    - MATIC

  exclude_stablecoins:
    - USDT
    - USDC
    - BUSD
    - DAI
    - TUSD
    - FDUSD

# 合约数据配置
futures:
  oi_change_period_minutes: 60  # OI变化计算周期
  max_funding_rate: 0.02        # Funding Rate阈值

# WebSocket配置
websocket:
  base_url: "wss://fstream.binance.com"
  mark_price_stream: "!markPrice@arr@1s"
  kline_interval: "5m"          # K线周期
  reconnect_delay: 5            # 重连延迟（秒）
  ping_interval: 180            # 心跳间隔（秒）
  max_reconnect_attempts: 10    # 最大重连次数

# 波动率配置
volatility:
  short_period: "5m"            # 短周期
  long_period_count: 12         # 长周期K线数量 (12 × 5m = 1h)
  volatility_ratio_threshold: 1.5   # 波动比阈值
  volume_ratio_threshold: 2.0       # 量比阈值

# 广场爬虫配置
square:
  scraper_mode: "playwright"
  posts_limit: 50
  timeout: 30
  max_retries: 3

# API限流
rate_limit:
  binance_futures: 20           # 每秒请求数

# 数据存储配置
storage:
  db_path: "data/shiit_long.db"
  retention_days: 7

# 日志配置
logging:
  level: "INFO"
  rotation: "10 MB"
  retention: "7 days"
```

## 7. 依赖包 (requirements.txt)

```
# HTTP客户端
aiohttp>=3.9.0
httpx>=0.27.0

# WebSocket
websockets>=12.0

# 配置管理
pyyaml>=6.0
python-dotenv>=1.0.0

# 爬虫相关
playwright>=1.40.0
beautifulsoup4>=4.12.0

# 日志
loguru>=0.7.0

# 定时任务
apscheduler>=3.10.0

# 类型支持
typing-extensions>=4.8.0
```

## 8. 数据采集流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        程序启动                                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
┌───────────────────────────┐     ┌───────────────────────────────┐
│   WebSocket 长连接 (常驻)   │     │      定时任务 (每3分钟)         │
│                           │     │                               │
│  Stream 1: markPrice      │     │  ┌─────────┐ ┌─────────────┐  │
│  ├─ Funding Rate (实时)   │     │  │ Market  │ │ OI          │  │
│  └─ Mark Price (实时)     │     │  │ REST    │ │ REST        │  │
│                           │     │  └────┬────┘ └──────┬──────┘  │
│  Stream 2: Top100 K线     │     │       │             │         │
│  └─ <symbol>@kline_5m     │     │       ▼             ▼         │
│     (动态订阅管理)         │     │  24h涨幅榜     OI/OI变化率    │
│                           │     │       │                       │
│  数据缓存到内存            │     │       └──→ 更新K线订阅列表    │
└───────────────┬───────────┘     └───────────────────────────────┘
                │                               │
                └───────────────┬───────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      波动率计算器                                  │
│  - 维护每个币种最近12根K线滑动窗口                                  │
│  - 计算: 5m振幅 / 1h均振幅 = 波动比                                │
│  - 计算: 5m成交量 / 1h均成交量 = 量比                              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CoinFilter                               │
│  - 排除BTC、ETH等主流币                                           │
│  - 排除稳定币（USDT、USDC等）                                      │
│  - 排除锚定币（股票代币、杠杆代币）                                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Storage                                 │
│  - 保存 market_snapshots                                         │
│  - 保存 futures_snapshots (含WebSocket数据)                       │
│  - 保存 klines (K线数据)                                          │
│  - 保存 square_hotness                                           │
│  - 写入 analysis_results (含波动率指标)                            │
└─────────────────────────────────────────────────────────────────┘
```

**数据源对比:**

| 数据 | 获取方式 | 频率 | 说明 |
|------|----------|------|------|
| Funding Rate | WebSocket | 实时 (1s) | `!markPrice@arr@1s` 全市场推送 |
| Mark Price | WebSocket | 实时 (1s) | 同上 |
| 5分钟K线 | WebSocket | 实时 (250ms) | `<symbol>@kline_5m` Top100动态订阅 |
| 24h Ticker | REST | 每3分钟 | 涨幅榜/价格/成交量 |
| Open Interest | REST | 每3分钟 | 无WSS支持 |
| 历史K线 | REST | 初始化时 | 获取过去1小时数据 |
| 广场热度 | 爬虫 | 每3分钟 | playwright |

## 9. 实现步骤

### Step 1: 项目基础设施
- 创建项目目录结构
- 创建 `requirements.txt`
- 创建 `config/config.yaml` 配置文件
- 实现 `src/config.py` 配置加载器
- 实现 `src/logger.py` 日志系统

### Step 2: 数据存储层
- 实现 `src/models.py` 数据模型 (dataclass)
- 实现 `src/storage.py` SQLite存储层
  - 表初始化
  - 快照存储
  - 历史查询
  - OI变化率计算

### Step 3: 行情数据采集器 (REST)
- 实现 `src/collectors/base.py` 基类
- 实现 `src/collectors/binance_market.py`
  - `GET /fapi/v1/ticker/24hr` 获取24h行情
  - 按涨幅排序取Top100
  - 价格/成交量数据

### Step 4: WebSocket 客户端
- 实现 `src/collectors/binance_ws.py`
  - 连接管理：Mark Price流 + Top100 K线流
  - 实时接收 Funding Rate / Mark Price / 5分钟K线
  - 动态订阅管理：根据涨幅榜变化调整K线订阅
  - 自动重连机制
  - 数据缓存到内存

### Step 5: 合约OI数据采集器 (REST)
- 实现 `src/collectors/binance_futures.py`
  - `GET /fapi/v1/openInterest` 实时OI
  - `GET /futures/data/openInterestHist` 历史OI
  - `GET /fapi/v1/klines` 历史K线（初始化用）
  - 计算 OI 变化率

### Step 6: 波动率计算器
- 实现 `src/analyzers/volatility.py`
  - 维护每个币种最近12根K线的滑动窗口
  - 计算5分钟振幅、1小时均振幅、波动比
  - 计算5分钟成交量、1小时均成交量、量比
  - 提供波动触发判断接口

### Step 7: 币安广场爬虫
- 实现 `src/collectors/binance_square.py`
  - playwright爬取热门帖子
  - 正则提取$Ticker提及
  - 计算热度评分

### Step 8: 币种过滤器
- 实现 `src/filters/coin_filter.py`
  - 排除主流币
  - 排除稳定币
  - 排除杠杆代币

### Step 9: 主程序与调度
- 实现 `main.py`
  - 启动 WebSocket 长连接 (Mark Price + K线)
  - 启动定时任务 (REST 轮询: 24h Ticker / OI)
  - 波动率实时计算
  - 数据聚合与存储

## 10. 风险与注意事项

### 10.1 API限流
- Binance Futures REST API: 1200 weight/min
- 需实现令牌桶限流器
- `/fapi/v1/ticker/24hr` (无参数): Weight 40
- `/fapi/v1/openInterest`: Weight 1/symbol

### 10.2 WebSocket 连接管理
- 币安服务器每3分钟发送 ping，需要 pong 响应
- 10分钟无 pong 会断开连接
- 单连接最多订阅 1024 个流
- 需实现自动重连机制
- 建议使用 `!markPrice@arr@1s` 全市场流，避免多次订阅

### 10.3 爬虫风险
- 币安广场可能有反爬机制
- 添加随机User-Agent
- 控制请求频率（10秒/次）
- HTML结构可能随时变化

### 10.4 数据一致性
- WebSocket 数据实时更新，REST 数据每3分钟更新
- 合并数据时使用统一时间戳
- 处理数据缺失情况
- 添加数据完整性检查
