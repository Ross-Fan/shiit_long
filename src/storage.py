"""
SQLite 数据存储层
持久化市场数据和广场热度数据
"""

import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from contextlib import contextmanager

from src.collectors.binance_market import TickerData
from src.collectors.binance_square import SquareHotness
from src.collectors.momentum import MomentumData
from src.signal import EntrySignal


class Database:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str = "data/shiit_long.db"):
        """
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    @contextmanager
    def _get_conn(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 市场快照表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    base_asset TEXT NOT NULL,
                    price REAL NOT NULL,
                    price_change_percent REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL NOT NULL,
                    rank INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 市场快照索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_snapshot_time
                ON market_snapshots(snapshot_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_symbol
                ON market_snapshots(symbol, snapshot_time)
            """)

            # 广场热度表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS square_hotness (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    view_count INTEGER NOT NULL,
                    discuss_count INTEGER NOT NULL,
                    hotness_score REAL NOT NULL,
                    success INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 广场热度索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_square_snapshot_time
                ON square_hotness(snapshot_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_square_symbol
                ON square_hotness(symbol, snapshot_time)
            """)

            # 采集任务记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collection_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time DATETIME NOT NULL,
                    market_count INTEGER DEFAULT 0,
                    square_count INTEGER DEFAULT 0,
                    square_success INTEGER DEFAULT 0,
                    momentum_count INTEGER DEFAULT 0,
                    momentum_success INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0,
                    status TEXT DEFAULT 'success',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 动能数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS momentum_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    base_asset TEXT NOT NULL,
                    current_price REAL NOT NULL,
                    current_volume REAL NOT NULL,
                    avg_volume_20 REAL NOT NULL,
                    volume_ratio REAL NOT NULL,
                    avg_price_5d REAL NOT NULL,
                    price_ratio REAL NOT NULL,
                    momentum_score REAL NOT NULL,
                    success INTEGER NOT NULL,
                    error_msg TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 动能数据索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_momentum_snapshot_time
                ON momentum_snapshots(snapshot_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_momentum_symbol
                ON momentum_snapshots(symbol, snapshot_time)
            """)

            # 数据库迁移：为旧表添加新列
            self._migrate_tables(cursor)

            # 入场信号表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entry_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_time DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    base_asset TEXT NOT NULL,
                    price REAL NOT NULL,
                    price_change_percent REAL NOT NULL,
                    rank INTEGER NOT NULL,
                    volume_ratio REAL NOT NULL,
                    price_ratio REAL NOT NULL,
                    momentum_score REAL NOT NULL,
                    view_count INTEGER DEFAULT 0,
                    discuss_count INTEGER DEFAULT 0,
                    signal_strength TEXT NOT NULL,
                    conditions_met TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 入场信号索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_time
                ON entry_signals(signal_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_symbol
                ON entry_signals(symbol, signal_time)
            """)

    def _migrate_tables(self, cursor):
        """数据库迁移：为旧表添加新列"""
        # 检查 collection_logs 表是否有 momentum_count 列
        cursor.execute("PRAGMA table_info(collection_logs)")
        columns = {row[1] for row in cursor.fetchall()}

        if "momentum_count" not in columns:
            cursor.execute("ALTER TABLE collection_logs ADD COLUMN momentum_count INTEGER DEFAULT 0")
        if "momentum_success" not in columns:
            cursor.execute("ALTER TABLE collection_logs ADD COLUMN momentum_success INTEGER DEFAULT 0")

    def save_market_snapshots(
        self,
        tickers: List[TickerData],
        snapshot_time: Optional[datetime] = None
    ) -> int:
        """
        保存市场快照数据

        Args:
            tickers: 行情数据列表（已按涨幅排序）
            snapshot_time: 快照时间，默认当前时间

        Returns:
            插入的记录数
        """
        if not tickers:
            return 0

        if snapshot_time is None:
            snapshot_time = datetime.now()

        with self._get_conn() as conn:
            cursor = conn.cursor()

            rows = [
                (
                    snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
                    t.symbol,
                    t.base_asset,
                    t.price,
                    t.price_change_percent,
                    t.volume,
                    t.quote_volume,
                    rank
                )
                for rank, t in enumerate(tickers, 1)
            ]

            cursor.executemany("""
                INSERT INTO market_snapshots
                (snapshot_time, symbol, base_asset, price, price_change_percent,
                 volume, quote_volume, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

            return len(rows)

    def save_square_hotness(
        self,
        hotness_list: List[SquareHotness],
        snapshot_time: Optional[datetime] = None
    ) -> int:
        """
        保存广场热度数据

        Args:
            hotness_list: 热度数据列表
            snapshot_time: 快照时间，默认当前时间

        Returns:
            插入的记录数
        """
        if not hotness_list:
            return 0

        if snapshot_time is None:
            snapshot_time = datetime.now()

        with self._get_conn() as conn:
            cursor = conn.cursor()

            rows = [
                (
                    snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
                    h.symbol,
                    h.view_count,
                    h.discuss_count,
                    h.hotness_score,
                    1 if h.success else 0
                )
                for h in hotness_list
            ]

            cursor.executemany("""
                INSERT INTO square_hotness
                (snapshot_time, symbol, view_count, discuss_count, hotness_score, success)
                VALUES (?, ?, ?, ?, ?, ?)
            """, rows)

            return len(rows)

    def save_momentum_snapshots(
        self,
        momentum_list: List[MomentumData],
        snapshot_time: Optional[datetime] = None
    ) -> int:
        """
        保存动能数据

        Args:
            momentum_list: 动能数据列表
            snapshot_time: 快照时间，默认当前时间

        Returns:
            插入的记录数
        """
        if not momentum_list:
            return 0

        if snapshot_time is None:
            snapshot_time = datetime.now()

        with self._get_conn() as conn:
            cursor = conn.cursor()

            rows = [
                (
                    snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
                    m.symbol,
                    m.base_asset,
                    m.current_price,
                    m.current_volume,
                    m.avg_volume_20,
                    m.volume_ratio,
                    m.avg_price_5d,
                    m.price_ratio,
                    m.momentum_score,
                    1 if m.success else 0,
                    m.error_msg
                )
                for m in momentum_list
            ]

            cursor.executemany("""
                INSERT INTO momentum_snapshots
                (snapshot_time, symbol, base_asset, current_price, current_volume,
                 avg_volume_20, volume_ratio, avg_price_5d, price_ratio,
                 momentum_score, success, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

            return len(rows)

    def log_collection(
        self,
        snapshot_time: datetime,
        market_count: int,
        square_count: int,
        square_success: int,
        duration_seconds: float,
        status: str = "success",
        error_message: Optional[str] = None,
        momentum_count: int = 0,
        momentum_success: int = 0
    ):
        """记录采集任务日志"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO collection_logs
                (snapshot_time, market_count, square_count, square_success,
                 momentum_count, momentum_success, duration_seconds, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
                market_count,
                square_count,
                square_success,
                momentum_count,
                momentum_success,
                duration_seconds,
                status,
                error_message
            ))

    def save_entry_signals(
        self,
        signals: List[EntrySignal]
    ) -> int:
        """
        保存入场信号

        Args:
            signals: 入场信号列表

        Returns:
            插入的记录数
        """
        if not signals:
            return 0

        with self._get_conn() as conn:
            cursor = conn.cursor()

            rows = [
                (
                    s.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                    s.symbol,
                    s.base_asset,
                    s.price,
                    s.price_change_percent,
                    s.rank,
                    s.volume_ratio,
                    s.price_ratio,
                    s.momentum_score,
                    s.view_count,
                    s.discuss_count,
                    s.signal_strength,
                    ", ".join(s.conditions_met)
                )
                for s in signals
            ]

            cursor.executemany("""
                INSERT INTO entry_signals
                (signal_time, symbol, base_asset, price, price_change_percent,
                 rank, volume_ratio, price_ratio, momentum_score,
                 view_count, discuss_count, signal_strength, conditions_met)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

            return len(rows)

    def get_latest_signals(self, limit: int = 20) -> List[dict]:
        """获取最近的入场信号"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM entry_signals
                ORDER BY signal_time DESC, momentum_score DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_market_snapshot(self) -> List[dict]:
        """获取最新一次市场快照"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM market_snapshots
                WHERE snapshot_time = (
                    SELECT MAX(snapshot_time) FROM market_snapshots
                )
                ORDER BY rank
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_square_hotness(self) -> List[dict]:
        """获取最新一次广场热度"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM square_hotness
                WHERE snapshot_time = (
                    SELECT MAX(snapshot_time) FROM square_hotness
                )
                ORDER BY hotness_score DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_momentum(self) -> List[dict]:
        """获取最新一次动能数据"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM momentum_snapshots
                WHERE snapshot_time = (
                    SELECT MAX(snapshot_time) FROM momentum_snapshots
                )
                ORDER BY momentum_score DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_collection_stats(self, limit: int = 10) -> List[dict]:
        """获取最近的采集统计"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM collection_logs
                ORDER BY snapshot_time DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_symbol_history(
        self,
        symbol: str,
        hours: int = 24
    ) -> dict:
        """
        获取指定币种的历史数据

        Args:
            symbol: 币种代码（如 PEPE）
            hours: 查询最近N小时

        Returns:
            包含 market 和 square 历史数据的字典
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 市场数据历史
            cursor.execute("""
                SELECT * FROM market_snapshots
                WHERE base_asset = ?
                AND snapshot_time >= datetime('now', ?)
                ORDER BY snapshot_time DESC
            """, (symbol, f'-{hours} hours'))
            market_history = [dict(row) for row in cursor.fetchall()]

            # 广场热度历史
            cursor.execute("""
                SELECT * FROM square_hotness
                WHERE symbol = ?
                AND snapshot_time >= datetime('now', ?)
                ORDER BY snapshot_time DESC
            """, (symbol, f'-{hours} hours'))
            square_history = [dict(row) for row in cursor.fetchall()]

            return {
                "symbol": symbol,
                "market": market_history,
                "square": square_history
            }


# 测试代码
if __name__ == "__main__":
    db = Database("data/test.db")

    # 测试保存
    from src.collectors.binance_market import TickerData
    from src.collectors.binance_square import SquareHotness

    test_tickers = [
        TickerData("PEPEUSDT", "PEPE", 0.00001, 15.5, 1000000, 50000000),
        TickerData("WIFUSDT", "WIF", 2.5, 12.3, 500000, 25000000),
    ]

    test_hotness = [
        SquareHotness("PEPE", 96600000, 93321, 94287.0, True),
        SquareHotness("WIF", 50000000, 45000, 45500.0, True),
    ]

    snapshot_time = datetime.now()

    n1 = db.save_market_snapshots(test_tickers, snapshot_time)
    n2 = db.save_square_hotness(test_hotness, snapshot_time)

    print(f"保存市场数据: {n1} 条")
    print(f"保存热度数据: {n2} 条")

    # 查询测试
    latest = db.get_latest_market_snapshot()
    print(f"\n最新市场快照: {len(latest)} 条")
    for row in latest:
        print(f"  {row['base_asset']}: {row['price_change_percent']:.2f}%")
