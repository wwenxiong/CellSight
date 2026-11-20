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
                "sector_radius_mode": "band_adaptive", # "fixed" | "band_adaptive"
                "color_mode": "rat",                   # "rat" | "freq_band" | "pci" | "alarm"
                "show_labels": True,
                "show_cell_sectors": True
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
    def pack_project_to_bytes(project_data: Dict[str, Any]) -> bytes:
        """将工程字典打包为 .wyp (ZIP 容器) 字节流"""
        project_data["meta"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            json_bytes = json.dumps(project_data, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("project.json", json_bytes)
            
            # 预留可分离存放大型轨迹或原始工参数据
            manifest = {
                "format": "wyp",
                "version": PROJECT_VERSION,
                "entry": "project.json",
                "cell_count": len(project_data.get("layers", {}).get("param_cells", []))
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            
        bio.seek(0)
        return bio.getvalue()

    @staticmethod
    def unpack_project_from_bytes(file_bytes: bytes) -> Dict[str, Any]:
        """从 .wyp 字节流解包并验证还原工程数据"""
        bio = io.BytesIO(file_bytes)
        try:
            with zipfile.ZipFile(bio, mode="r") as zf:
                if "project.json" in zf.namelist():
                    content = zf.read("project.json").decode("utf-8")
                    return json.loads(content)
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
