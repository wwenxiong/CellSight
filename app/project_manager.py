# -*- coding: utf-8 -*-
"""
Wmap 专属工程文件 (.wyp) 管理器
负责工程的新建、加载、保存、序列化与解包，自包含保存视窗、图层、工参、样式与标注数据
"""

import os
import io
import json
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

PROJECT_VERSION = "Wmap-1.0"
DEFAULT_PROJECT_NAME = "未命名网优工程"

class ProjectManager:
    """Wmap 工程文件 (.wyp) 序列化与读写引擎"""

    @staticmethod
    def create_empty_project(name: str = DEFAULT_PROJECT_NAME) -> Dict[str, Any]:
        """创建一个全新的空白网优工程结构"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "meta": {
                "name": name,
                "version": PROJECT_VERSION,
                "created_at": now_str,
                "updated_at": now_str,
                "description": "Wmap 无线网优地图工程文件"
            },
            "view_state": {
                "center": [113.3245, 23.1234],
                "zoom": 13,
                "tile_type": "amap_dark"
            },
            "style_config": {
                "sector_beamwidth": 65,
                "sector_radius_scale": 1.0,            # 扇区整体大小缩放比例 (默认 1.0)
                "sector_radius_mode": "band_adaptive", # "fixed" | "band_adaptive"
                "color_mode": "rat",                   # "rat" | "freq_band" | "pci" | "alarm"
                "show_labels": True,
                "show_cell_sectors": True,
                "layer_label_fields": {},              # 按图层自定义扇区标注显示字段
                "layer_label_lengths": {},             # 按图层自定义扇区标注字段长度截断限制
                "layer_label_visibility": {},          # 按图层自定义扇区标注字段显示/隐藏开关
                "layer_colors": {}                     # 按图层自定义扇区基础颜色
            },
            "layers": {
                "param_cells": [],      # 全量导入的工参小区
                "annotations": [],      # 标注图层（点、线、多边形、测距注记）
                "emergency_selection": {
                    "geometry": None,   # 圈选多边形或圆形参数
                    "selected_cells": [],
                    "matched_alarms": [],
                    "matched_kpi": [],
                    "diagnosed_cells": []
                }
            }
        }

    @staticmethod
    def pack_project_to_bytes(
        project_data: Dict[str, Any], 
        db_path: Optional[str] = None,
        db_bytes: Optional[bytes] = None
    ) -> bytes:
        """将工程字典打包为 .wyp (ZIP 容器) 字节流，同时打包 SQLite 数据库文件"""
        project_data["meta"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        raw_cell_count = len(project_data.get("layers", {}).get("param_cells", []))
        has_db_payload = bool(db_bytes) or bool(db_path and Path(db_path).exists())

        # 当已打包 SQLite 数据库时，project.json 不再重复冗余存储 param_cells 与全量 selected_cells 副本
        json_payload = project_data
        if has_db_payload and raw_cell_count > 0:
            json_payload = dict(project_data)
            layers_copy = dict(project_data.get("layers", {}))
            layers_copy["param_cells"] = []
            em_sel = layers_copy.get("emergency_selection")
            if isinstance(em_sel, dict):
                sel_cells = em_sel.get("selected_cells", [])
                if isinstance(sel_cells, list) and len(sel_cells) >= raw_cell_count:
                    em_copy = dict(em_sel)
                    em_copy["selected_cells"] = []
                    layers_copy["emergency_selection"] = em_copy
            json_payload["layers"] = layers_copy

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            json_bytes = json.dumps(json_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            zf.writestr("project.json", json_bytes)

            # 打包 SQLite 数据库文件 (cells.db)
            packaged_db = False
            if db_bytes:
                zf.writestr("cells.db", db_bytes)
                packaged_db = True
            elif db_path and Path(db_path).exists():
                zf.write(str(db_path), arcname="cells.db")
                packaged_db = True

            manifest = {
                "format": "wyp",
                "version": PROJECT_VERSION,
                "entry": "project.json",
                "has_sqlite_db": packaged_db,
                "cell_count": raw_cell_count
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            
        bio.seek(0)
        return bio.getvalue()

    @staticmethod
    def _parse_project_json_fast(raw_text: str, has_sqlite_db: bool) -> Dict[str, Any]:
        """当工程包内已含 cells.db 且 project.json 体积庞大时，跳过冗余大数组秒级解析元数据。"""
        if has_sqlite_db and len(raw_text) > 1_000_000:
            text = raw_text
            # 1. 跳过超大的 emergency_selection.selected_cells（在后半段，先替换避免偏移失效）
            sc_idx = text.rfind('"selected_cells"')
            if sc_idx != -1:
                sc_start = text.find("[", sc_idx)
                ma_idx = text.rfind('"matched_alarms"')
                if sc_start != -1 and ma_idx > sc_start and (ma_idx - sc_start) > 500_000:
                    sc_end = text.rfind("]", sc_start, ma_idx)
                    if sc_end != -1:
                        text = text[:sc_start + 1] + text[sc_end:]

            # 2. 跳过超大的 layers.param_cells
            key_idx = text.find('"param_cells"')
            if key_idx != -1:
                bracket_start = text.find("[", key_idx)
                ann_idx = text.rfind('"annotations"')
                if bracket_start != -1 and ann_idx > bracket_start:
                    bracket_end = text.rfind("]", bracket_start, ann_idx)
                    if bracket_end != -1:
                        text = text[:bracket_start + 1] + text[bracket_end:]

            return json.loads(text)
        return json.loads(raw_text)

    @staticmethod
    def _load_sqlite_fast(db_path: Path):
        """原生 sqlite3 极速读取 cells 表，同时返回 (DataFrame, param_table)。"""
        import sqlite3
        import math
        import pandas as pd

        if not db_path.exists():
            return pd.DataFrame(), {"columns": [], "rows": []}

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cells'")
            if not cursor.fetchone():
                return pd.DataFrame(), {"columns": [], "rows": []}
            cursor.execute("SELECT * FROM cells")
            columns = [desc[0] for desc in cursor.description]
            raw_rows = cursor.fetchall()

        if not raw_rows:
            return pd.DataFrame(columns=columns), {"columns": columns, "rows": []}

        # 清洗浮点 NaN/Inf 确保 JSON 合规
        isnan = math.isnan
        isinf = math.isinf
        clean_rows = []
        for r in raw_rows:
            has_bad = False
            for v in r:
                if type(v) is float and (isnan(v) or isinf(v)):
                    has_bad = True
                    break
            if has_bad:
                clean_rows.append([None if (type(v) is float and (isnan(v) or isinf(v))) else v for v in r])
            else:
                clean_rows.append(list(r))

        df = pd.DataFrame.from_records(clean_rows, columns=columns)
        for num_col in ("longitude", "latitude", "azimuth", "tilt", "height", "longitude_gcj", "latitude_gcj"):
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

        return df, {"columns": columns, "rows": clean_rows}

    @classmethod
    def unpack_project_with_meta(
        cls,
        file_bytes: bytes,
        extract_db_path: Optional[str] = None,
        prefer_table: bool = False,
    ):
        """解包 .wyp 并返回 (project_data, restored_from_db, preloaded_df)，避免后续重复写库与重读。"""
        from app.cell_db import DEFAULT_DB_PATH, CellDB

        bio = io.BytesIO(file_bytes)
        restored_from_db = False
        preloaded_df = None
        try:
            with zipfile.ZipFile(bio, mode="r") as zf:
                namelist = set(zf.namelist())
                has_db = "cells.db" in namelist

                # 1. 优先提取 SQLite 数据库文件
                target_db = Path(extract_db_path) if extract_db_path else DEFAULT_DB_PATH
                if has_db:
                    target_db.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open("cells.db") as src, open(target_db, "wb") as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
                    restored_from_db = True
                    logger.info("已从 .wyp 工程成功提取恢复 SQLite 数据库: %s", target_db)

                # 2. 解析 project.json（有 cells.db 且是大文件时自动跳过冗余 param_cells）
                project_data = None
                if "project.json" in namelist:
                    content = zf.read("project.json").decode("utf-8")
                    project_data = cls._parse_project_json_fast(content, has_sqlite_db=has_db)

                # 3. 装载工参数据
                if project_data:
                    layers = project_data.setdefault("layers", {})
                    existing_cells = layers.get("param_cells", [])
                    if has_db and not existing_cells:
                        df, table_payload = cls._load_sqlite_fast(target_db)
                        preloaded_df = df
                        if prefer_table:
                            layers["param_cells"] = []
                            layers["param_table"] = table_payload
                        elif not df.empty:
                            layers["param_cells"] = CellDB.to_records(df)
                    elif existing_cells:
                        layers["param_cells"] = CellDB.sanitize_records(existing_cells)
                        if prefer_table:
                            import pandas as pd
                            df = pd.DataFrame(layers["param_cells"])
                            preloaded_df = df
                            cols = list(df.columns)
                            layers["param_table"] = {
                                "columns": cols,
                                "rows": [[row.get(c) for c in cols] for row in layers["param_cells"]],
                            }
                            layers["param_cells"] = []

                    return project_data, restored_from_db, preloaded_df
        except zipfile.BadZipFile:
            # 兼容纯 JSON 格式工程文件
            try:
                content = file_bytes.decode("utf-8")
                return json.loads(content), False, None
            except Exception as e:
                raise ValueError(f"无法解析 .wyp 工程文件: {e}")
        raise ValueError("非法的 Wmap 工程文件，缺少核心 project.json 数据")

    @staticmethod
    def unpack_project_from_bytes(
        file_bytes: bytes, 
        extract_db_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """从 .wyp 字节流解包并验证还原工程数据，若包含 cells.db 则提取恢复 SQLite 数据库"""
        project_data, _, _ = ProjectManager.unpack_project_with_meta(file_bytes, extract_db_path=extract_db_path)
        return project_data

    @classmethod
    def save_project_to_disk(cls, project_data: Dict[str, Any], target_path: str) -> str:
        data_bytes = cls.pack_project_to_bytes(project_data)
        out_p = Path(target_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "wb") as f:
            f.write(data_bytes)
        return str(out_p.resolve())

    @classmethod
    def load_project_from_disk(cls, target_path: str) -> Dict[str, Any]:
        with open(target_path, "rb") as f:
            data_bytes = f.read()
        return cls.unpack_project_from_bytes(data_bytes)
