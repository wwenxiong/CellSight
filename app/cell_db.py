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
                    # 优先针对有效非空 CGI 执行去重更新，避免空 CGI 互相误删
                    if "cgi" in combined.columns:
                        cgi_clean = combined["cgi"].astype(str).str.strip()
                        valid_cgi = cgi_clean.ne("") & cgi_clean.str.lower().ne("nan") & cgi_clean.str.lower().ne("none")
                        if valid_cgi.any():
                            valid_part = combined[valid_cgi].drop_duplicates(subset=["cgi"], keep="last")
                            invalid_part = combined[~valid_cgi]
                            combined = pd.concat([invalid_part, valid_part], ignore_index=True)

                    if "layer_name" in combined.columns and "cell_name" in combined.columns:
                        combined = combined.drop_duplicates(subset=["layer_name", "cell_name"], keep="last")
                    elif "cell_name" in combined.columns and "rat" in combined.columns:
                        combined = combined.drop_duplicates(subset=["cell_name", "rat"], keep="last")
                    elif "cell_name" in combined.columns:
                        combined = combined.drop_duplicates(subset=["cell_name"], keep="last")
                    save_df = combined
            except Exception as e:
                logger.warning("追加工参模式合并异常，回退为覆盖模式: %s", e)

        # 保证所有列名在 SQLite 中不重复（SQLite 列名不区分大小写）
        core_keys = {
            "cell_name", "site_name", "longitude", "latitude", "azimuth",
            "tilt", "height", "pci", "cell_id", "site_id", "cgi",
            "freq_band", "cover_type", "rat", "layer_name", "longitude_gcj", "latitude_gcj"
        }
        raw_cols = list(save_df.columns)
        core_in_df = {c for c in raw_cols if c in core_keys}
        cols_to_keep = []
        for c in raw_cols:
            c_low = str(c).strip().lower()
            # 若存在同名核心标准键（如 pci 与 PCI），丢弃大写变体，保留小写标准键
            if c_low in core_keys and c != c_low and c_low in core_in_df:
                continue
            cols_to_keep.append(c)

        save_df = save_df.loc[:, cols_to_keep].copy()

        # 再次消解可能依然存在的同名或大小写重复列（如原表格中有重复列）
        final_cols = []
        seen_lower = set()
        for c in save_df.columns:
            c_str = str(c).strip()
            c_low = c_str.lower()
            if c_low not in seen_lower:
                seen_lower.add(c_low)
                final_cols.append(c_str)
            else:
                counter = 2
                cand = f"{c_str}_{counter}"
                while cand.lower() in seen_lower:
                    counter += 1
                    cand = f"{c_str}_{counter}"
                seen_lower.add(cand.lower())
                final_cols.append(cand)
        save_df.columns = final_cols

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

    @staticmethod
    def sanitize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """清洗记录列表，保证 JSON 可序列化：NaN/Inf 转 None，numpy 标量转原生类型。

        DataFrame.to_dict() 会带出 float('nan') 与 np.int64 等值，Starlette 的
        JSONResponse（allow_nan=False）序列化响应时会抛
        "Out of range float values are not JSON compliant: nan"。
        """
        clean_records: List[Dict[str, Any]] = []
        for row in records or []:
            clean: Dict[str, Any] = {}
            for k, v in row.items():
                if v is None:
                    clean[k] = None
                elif isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")):
                    clean[k] = None
                elif pd.isna(v):
                    clean[k] = None
                elif hasattr(v, "item") and not isinstance(v, (str, bytes)):
                    try:
                        clean[k] = v.item()
                    except Exception:
                        clean[k] = v
                else:
                    clean[k] = v
            clean_records.append(clean)
        return clean_records

    @classmethod
    def to_records(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """DataFrame 转 JSON 安全的记录列表（NaN/Inf 转 None，numpy 标量转原生类型）。"""
        if df is None or df.empty:
            return []
        return cls.sanitize_records(df.to_dict(orient="records"))

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

                # 图层统计
                layers = []
                if "layer_name" in col_names:
                    cursor.execute("SELECT layer_name, COUNT(*) FROM cells GROUP BY layer_name")
                    for r in cursor.fetchall():
                        layers.append({"name": r[0] or "工参图层", "count": r[1]})

                return {
                    "total_cells": total_cells,
                    "total_sites": total_sites,
                    "lte_cells": lte_cells,
                    "nr_cells": nr_cells,
                    "layers": layers
                }
        except Exception as e:
            logger.warning("获取 SQLite 工参摘要异常: %s", e)
            return {"total_cells": 0, "total_sites": 0, "lte_cells": 0, "nr_cells": 0, "layers": []}

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
