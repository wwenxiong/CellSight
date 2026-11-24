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
        from app.cell_db import DEFAULT_DB_PATH, CellDB

        project_data["meta"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            json_bytes = json.dumps(project_data, ensure_ascii=False, indent=2).encode("utf-8")
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
                "cell_count": len(project_data.get("layers", {}).get("param_cells", []))
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            
        bio.seek(0)
        return bio.getvalue()

    @staticmethod
    def unpack_project_from_bytes(
        file_bytes: bytes, 
        extract_db_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """从 .wyp 字节流解包并验证还原工程数据，若包含 cells.db 则提取恢复 SQLite 数据库"""
        from app.cell_db import DEFAULT_DB_PATH, CellDB

        bio = io.BytesIO(file_bytes)
        try:
            with zipfile.ZipFile(bio, mode="r") as zf:
                project_data = None
                if "project.json" in zf.namelist():
                    content = zf.read("project.json").decode("utf-8")
                    project_data = json.loads(content)

                # 恢复内嵌的 SQLite 数据库文件
                if "cells.db" in zf.namelist():
                    target_db = Path(extract_db_path) if extract_db_path else DEFAULT_DB_PATH
                    target_db.parent.mkdir(parents=True, exist_ok=True)
                    db_bytes = zf.read("cells.db")
                    target_db.write_bytes(db_bytes)
                    logger.info("已从 .wyp 工程成功提取恢复 SQLite 数据库: %s (%d 字节)", target_db, len(db_bytes))

                    # 若 JSON 中的 param_cells 为空，直接从恢复的 SQLite 读取填入
                    # （to_records 会把 NaN/Inf 转 None、numpy 标量转原生类型，
                    #  否则 Starlette JSONResponse 序列化响应时会报
                    #  "Out of range float values are not JSON compliant: nan"）
                    if project_data:
                        existing_cells = project_data.get("layers", {}).get("param_cells", [])
                        if not existing_cells:
                            df = CellDB.load_dataframe(target_db)
                            if not df.empty:
                                project_data.setdefault("layers", {})["param_cells"] = CellDB.to_records(df)

                # 清洗 project.json 自带的 param_cells：旧工程文件里可能已存有 NaN
                # 字面量（之前打包时未经清洗），同样会在响应序列化时报错
                if project_data:
                    layers = project_data.setdefault("layers", {})
                    if layers.get("param_cells"):
                        layers["param_cells"] = CellDB.sanitize_records(layers["param_cells"])

                if project_data:
                    return project_data
        except zipfile.BadZipFile:
            # 兼容纯 JSON 格式工程文件
            try:
                content = file_bytes.decode("utf-8")
                return json.loads(content)
            except Exception as e:
                raise ValueError(f"无法解析 .wyp 工程文件: {e}")
        raise ValueError("非法的 Wmap 工程文件，缺少核心 project.json 数据")

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
