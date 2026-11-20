# -*- coding: utf-8 -*-
"""
Wmap SQLite 工参存储引擎
支持动态表头存储、保留导入表格的所有原始列、高速索引与工程自包含打包
"""
import os
import json
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "wmap_cells.db"


class CellDB:
    """SQLite 工参持久化管理器"""

    @classmethod
    def get_connection(cls, db_path: Optional[Path] = None) -> sqlite3.Connection:
        path = db_path or DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def save_dataframe(
        cls, 
        df: pd.DataFrame, 
        db_path: Optional[Path] = None,
        field_mapping: Optional[Dict[str, str]] = None,
        mode: str = "replace"
    ) -> int:
        """
        将工参 DataFrame 保存至 SQLite 数据库。
        完全保留导入文件中的所有原始表头和列数据，不提前限制表头。
        mode: 'replace' 覆盖现有工参，'append' 追加合并现有工参
        """
        if df is None or df.empty:
            logger.warning("尝试保存空的工参 DataFrame 到 SQLite")
            return 0

        path = db_path or DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        save_df = df.copy()

        # 追加模式下合并已有工参
        if mode == "append" and path.exists() and path.stat().st_size > 0:
            try:
                old_df = cls.load_dataframe(path)
                if not old_df.empty:
                    combined = pd.concat([old_df, save_df], ignore_index=True)
                    # 优先依据 cgi 覆盖更新，其次依据 cell_name + rat
                    if "cgi" in combined.columns and combined["cgi"].astype(str).str.strip().ne("").any():
                        combined = combined.drop_duplicates(subset=["cgi"], keep="last")
                    elif "cell_name" in combined.columns and "rat" in combined.columns:
                        combined = combined.drop_duplicates(subset=["cell_name", "rat"], keep="last")
                    save_df = combined
            except Exception as e:
                logger.warning("追加工参模式合并异常，回退为覆盖模式: %s", e)

        with sqlite3.connect(str(path)) as conn:
            # 1. 原样保存所有列（包含用户自定义表头）
            for col in save_df.columns:
                # 复杂对象统一转为字符串，保证兼容性
                if save_df[col].dtype == object:
                    save_df[col] = save_df[col].fillna("").astype(str)

            save_df.to_sql("cells", conn, if_exists="replace", index=False)

            # 2. 建立常用查询索引（若对应列存在）
            cursor = conn.cursor()
            cols = [c.lower() for c in save_df.columns]
            if "longitude" in cols and "latitude" in cols:
                try:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cells_coords ON cells (longitude, latitude)")
                except Exception:
                    pass
            if "cell_id" in cols:
                try:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cells_cell_id ON cells (cell_id)")
                except Exception:
                    pass
            if "cell_name" in cols:
                try:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cells_cell_name ON cells (cell_name)")
                except Exception:
                    pass

            # 3. 存储元数据
            cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            cursor.execute("INSERT OR REPLACE INTO meta VALUES ('total_rows', ?)", (str(len(save_df)),))
            cursor.execute("INSERT OR REPLACE INTO meta VALUES ('columns', ?)", (json.dumps(list(df.columns), ensure_ascii=False),))
            if field_mapping:
                cursor.execute("INSERT OR REPLACE INTO meta VALUES ('field_mapping', ?)", (json.dumps(field_mapping, ensure_ascii=False),))
            cursor.execute("INSERT OR REPLACE INTO meta VALUES ('updated_at', datetime('now', 'localtime'))")
            conn.commit()

        logger.info("已将 %d 条工参（%d 个字段）存入 SQLite: %s", len(df), len(df.columns), path)
        return len(df)

    @classmethod
    def load_dataframe(cls, db_path: Optional[Path] = None) -> pd.DataFrame:
        """从 SQLite 加载全量工参 DataFrame（包含导入的所有原始表头）"""
        path = db_path or DEFAULT_DB_PATH
        if not path.exists():
            return pd.DataFrame()

        try:
            with sqlite3.connect(str(path)) as conn:
                df = pd.read_sql("SELECT * FROM cells", conn)
                # 转换经纬度、方位角等数值列
                for num_col in ["longitude", "latitude", "azimuth", "tilt", "height"]:
                    if num_col in df.columns:
                        df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
                for gcj_col in ["longitude_gcj", "latitude_gcj"]:
                    if gcj_col in df.columns:
                        df[gcj_col] = pd.to_numeric(df[gcj_col], errors="coerce")
                return df
        except Exception as e:
            logger.error("从 SQLite 读取工参失败: %s", e)
            return pd.DataFrame()

    @classmethod
    def get_summary(cls, db_path: Optional[Path] = None) -> Dict[str, Any]:
        """获取 SQLite 中的工参统计信息"""
        path = db_path or DEFAULT_DB_PATH
        if not path.exists():
            return {"total_cells": 0, "total_sites": 0, "lte_cells": 0, "nr_cells": 0}

        try:
            with sqlite3.connect(str(path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM cells")
                row = cursor.fetchone()
                total_cells = row[0] if row else 0

                # 站点统计
                total_sites = total_cells
                cols_query = cursor.execute("PRAGMA table_info(cells)").fetchall()
                col_names = [r[1].lower() for r in cols_query]

                if "site_name" in col_names:
                    cursor.execute("SELECT COUNT(DISTINCT site_name) FROM cells")
                    total_sites = cursor.fetchone()[0]
                elif "site_id" in col_names:
                    cursor.execute("SELECT COUNT(DISTINCT site_id) FROM cells")
                    total_sites = cursor.fetchone()[0]

                # 制式统计
                lte_cells = 0
                nr_cells = 0
                if "rat" in col_names:
                    cursor.execute("SELECT COUNT(*) FROM cells WHERE UPPER(rat) LIKE '%5G%' OR UPPER(rat) LIKE '%NR%'")
                    nr_cells = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(*) FROM cells WHERE UPPER(rat) LIKE '%4G%' OR UPPER(rat) LIKE '%LTE%'")
                    lte_cells = cursor.fetchone()[0]

                return {
                    "total_cells": total_cells,
                    "total_sites": total_sites,
                    "lte_cells": lte_cells,
                    "nr_cells": nr_cells
                }
        except Exception as e:
            logger.warning("获取 SQLite 工参摘要异常: %s", e)
            return {"total_cells": 0, "total_sites": 0, "lte_cells": 0, "nr_cells": 0}

    @classmethod
    def get_db_bytes(cls, db_path: Optional[Path] = None) -> bytes:
        """获取 SQLite 数据库文件的二进制字节流（用于打包进 .wyp 工程）"""
        path = db_path or DEFAULT_DB_PATH
        if path.exists():
            return path.read_bytes()
        return b""

    @classmethod
    def restore_db_bytes(cls, data: bytes, db_path: Optional[Path] = None) -> Path:
        """从二进制字节流恢复 SQLite 数据库文件（用于从 .wyp 工程解包）"""
        path = db_path or DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info("已恢复 SQLite 数据库文件: %s (%d 字节)", path, len(data))
        return path
