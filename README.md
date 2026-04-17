# Shiit Long - 山寨币合约做多数据采集

山寨币合约动能追踪系统的数据采集模块，用于获取 Binance Futures 涨幅榜和币安广场热度数据。

## 功能

- **涨幅榜采集**: 获取 Binance Futures 24h 涨幅榜 Top50（排除主流币/稳定币）
- **广场热度爬虫**: 按币种抓取币安广场的浏览量和讨论数

## 环境要求

- Python 3.9+
- 网络可访问 Binance API 和网站

## 安装部署

### 1. 克隆项目

```bash
cd /your/path
git clone <repo_url> shiit_long
cd shiit_long
```

### 2. 创建虚拟环境（推荐）

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装 Playwright 浏览器

```bash
python3 -m playwright install chromium
```

> 如果在无头服务器上安装失败，可能需要先安装系统依赖：
> ```bash
> # Ubuntu/Debian
> sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
>     libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
>     libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
> ```
或者:
```bash
python3 -m playwright install-deps chromium
```

## 使用方法

### 启动主程序（推荐）

```bash
# 启动定时服务（默认每15分钟执行一次）
python shiit_long_main.py

# 自定义执行间隔（每30分钟）
python shiit_long_main.py --interval=30

# 只执行一次（不启动定时任务）
python shiit_long_main.py --once

# 自定义热度抓取数量（默认20个）
python shiit_long_main.py --square-limit=10

# 后台运行
nohup python3 shiit_long_main.py > logs/shiit_long.log 2>&1 &

# 查看帮助
python shiit_long_main.py --help
```

### 快速测试

```bash
# 测试涨幅榜采集
python -m src.collectors.binance_market

# 测试广场热度爬虫
python -m src.collectors.binance_square

# 完整测试（涨幅榜 + 广场热度）
python test_collectors.py
```

### 代码调用

```python
import asyncio
from src.collectors.binance_market import BinanceMarketCollector
from src.collectors.binance_square import BinanceSquareCollector

async def main():
    # 1. 获取涨幅榜 Top50
    market = BinanceMarketCollector()
    top_gainers = await market.get_top_gainers(50)
    await market.close()

    for t in top_gainers[:10]:
        print(f"{t.base_asset}: {t.price_change_percent:.2f}%")

    # 2. 抓取广场热度
    symbols = [t.base_asset for t in top_gainers[:10]]

    square = BinanceSquareCollector(delay=3.0)  # 3秒间隔
    results = await square.fetch_batch_hotness(symbols)
    await square.close()

    for r in results:
        if r.success:
            print(f"{r.symbol}: views={r.view_count:,}, discuss={r.discuss_count:,}")
        else:
            print(f"{r.symbol}: 抓取失败")

asyncio.run(main())
```

## 项目结构

```
shiit_long/
├── README.md               # 本文件
├── requirements.txt        # Python 依赖
├── design.md              # 详细设计文档
├── shiit_long_main.py      # 主程序入口（定时采集）
├── test_collectors.py      # 测试脚本
│
├── src/
│   ├── __init__.py
│   ├── storage.py          # SQLite 数据存储层
│   └── collectors/
│       ├── __init__.py
│       ├── binance_market.py   # 涨幅榜采集器
│       └── binance_square.py   # 广场热度爬虫
│
├── data/
│   └── shiit_long.db       # SQLite 数据库
└── logs/                   # 日志目录
```

## 数据结构

### TickerData（涨幅榜数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 交易对，如 PEPEUSDT |
| base_asset | str | 币种，如 PEPE |
| price | float | 当前价格 |
| price_change_percent | float | 24h 涨跌幅 (%) |
| volume | float | 24h 成交量 |
| quote_volume | float | 24h 成交额 (USDT) |

### SquareHotness（广场热度数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 币种，如 PEPE |
| view_count | int | 话题浏览量（-1 表示失败） |
| discuss_count | int | 话题讨论数（-1 表示失败） |
| hotness_score | float | 热度评分 |
| success | bool | 是否抓取成功 |

## 配置说明

### 广场爬虫延迟

```python
# 默认 3 秒间隔，避免被封
collector = BinanceSquareCollector(delay=3.0)

# 服务器稳定后可适当减少
collector = BinanceSquareCollector(delay=2.0)
```

### 排除币种列表

在 `binance_market.py` 中可修改：

```python
# 排除的主流币
EXCLUDE_MAJORS = {'BTC', 'ETH', 'BNB', ...}

# 排除的稳定币
EXCLUDE_STABLECOINS = {'USDT', 'USDC', ...}
```

## 注意事项

1. **广场爬虫限流**: 默认 3 秒间隔，50 个币种约需 2.5 分钟
2. **失败处理**: 爬虫失败时返回 `success=False`，数值为 `-1`
3. **页面变化**: 币安广场页面结构可能变化，需定期维护选择器
4. **无需登录**: 广场 hashtag 页面公开可访问
5. **API 限流**: Binance Futures API 限制 1200 weight/min，当前使用量很低

## 后续开发

- [ ] WebSocket 实时数据（Funding Rate / K线）
- [x] SQLite 数据存储
- [ ] 波动率计算
- [ ] 入场信号生成
- [x] 定时任务调度

## 故障排查

### Playwright 安装失败

```bash
# 查看详细错误
python -m playwright install chromium --with-deps

# 或手动下载
python -m playwright install-deps
```

### 广场抓取全为 0

可能原因：
1. 页面结构变化 - 检查 `debug_square.py` 输出
2. 网络问题 - 确认能访问 binance.com
3. 币种不存在 - 该币种在广场无 hashtag 页面

### API 请求失败

```bash
# 测试网络连通性
curl https://fapi.binance.com/fapi/v1/ticker/24hr
```

## License

MIT
