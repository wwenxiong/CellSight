# -*- coding: utf-8 -*-
"""
智能工参导入引擎 - 支持 Excel / CSV 无固定模板导入、智能表头推断与映射记忆
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

from app.coord_utils import wgs84_to_gcj02, gcj02_to_wgs84

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 标准化字段定义与丰富别名字典
# ---------------------------------------------------------------------------
STANDARD_FIELD_DEFINITIONS = [
    {
        "key": "cell_name",
        "name": "小区名称",
        "required": True,
        "aliases": ["小区名称", "小区名", "小区中文名", "扇区名", "CELL_NAME", "CELLNAME", "CELL_NAME_CH", "小区"]
    },
    {
        "key": "site_name",
        "name": "基站名称",
        "required": False,
        "aliases": ["基站名称", "站名", "站点名称", "物理站名", "ENODEB_NAME", "GNB_NAME", "站址名称", "SITE_NAME", "SITENAME", "BTS_NAME"]
    },
    {
        "key": "longitude",
        "name": "经度",
        "required": True,
        "aliases": ["经度", "站址经度", "基站经度", "天线经度", "LON", "LONGITUDE", "LNG", "X", "经度(度)", "经度（度）"]
    },
    {
        "key": "latitude",
        "name": "纬度",
        "required": True,
        "aliases": ["纬度", "站址纬度", "基站纬度", "天线纬度", "LAT", "LATITUDE", "Y", "纬度(度)", "纬度（度）"]
    },
    {
        "key": "azimuth",
        "name": "方位角",
        "required": False,
        "aliases": ["方位角", "天线方位角", "方向角", "AZIMUTH", "AZI", "方向", "天线方向", "天线角度", "DIR"]
    },
    {
        "key": "freq_band",
        "name": "频段/频点",
        "required": False,
        "aliases": ["频段", "频点", "工作频段", "FREQ_BAND", "BAND", "EARFCN", "NR-ARFCN", "ARFCN", "频率", "中心频点"]
    },
    {
        "key": "pci",
        "name": "PCI",
        "required": False,
        "aliases": ["PCI", "物理小区标识", "物理小区ID", "PHY_CELL_ID", "PHYSICAL_CELL_ID"]
    },
    {
        "key": "cell_id",
        "name": "小区ID",
        "required": False,
        "aliases": ["小区编号", "小区ID", "CELL_ID", "CELLID", "LOCAL_CELL_ID", "LOCALCELLID", "CI", "本地小区标识"]
    },
    {
        "key": "site_id",
        "name": "基站ID",
        "required": False,
        "aliases": ["基站编号", "基站ID", "ENODEB_ID", "ENODEBID", "GNB_ID", "GNBID", "站号", "SITE_ID", "SITEID", "站址编码"]
    },
    {
        "key": "cgi",
        "name": "CGI/ECGI/NCGI",
        "required": False,
        "aliases": ["CGI", "ECGI", "NCGI", "E-CGI", "N-CGI", "全球小区标识", "全球小区ID"]
    },
    {
        "key": "tilt",
        "name": "下倾角",
        "required": False,
        "aliases": ["下倾角", "总下倾角", "电下倾角", "机械下倾", "TILT", "电子下倾角", "总下倾"]
    },
    {
        "key": "height",
        "name": "挂高(m)",
        "required": False,
        "aliases": ["挂高", "天线挂高", "高度", "海拔高度", "HEIGHT", "ANT_HEIGHT", "天线高度"]
    },
    {
        "key": "cover_type",
        "name": "覆盖场景",
        "required": False,
        "aliases": ["覆盖类型", "覆盖场景", "室内外", "COVER_TYPE", "场景", "分布系统", "室分"]
    }
]

TEMPLATE_STORAGE_FILE = Path(__file__).resolve().parent.parent / "data" / "smart_mapping_templates.json"

class SmartImporter:
    """智能工参解析与映射管理器"""

    @staticmethod
    def load_templates() -> Dict[str, Dict[str, str]]:
        if TEMPLATE_STORAGE_FILE.exists():
            try:
                with open(TEMPLATE_STORAGE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载映射模板失败: {e}")
        return {}

    @staticmethod
    def save_template(name: str, mapping: Dict[str, str]):
        templates = SmartImporter.load_templates()
        templates[name] = mapping
        TEMPLATE_STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(TEMPLATE_STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存映射模板失败: {e}")

    @staticmethod
    def read_raw_dataframe(file_path: str, max_rows: Optional[int] = None) -> pd.DataFrame:
        """支持 CSV、XLSX、XLS 并自动识别多种中文编码"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path, nrows=max_rows)
            return df
        
        # CSV 编码回退尝试
        encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312", "latin1"]
        last_err = None
        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc, nrows=max_rows, low_memory=False)
                return df
            except Exception as e:
                last_err = e
                continue
        raise ValueError(f"无法读取表格文件，所有编码尝试均失败: {last_err}")

    @classmethod
    def analyze_file(cls, file_path: str) -> Dict[str, Any]:
        """读取文件头几行并智能匹配字段，返回预测的映射关系与预览数据"""
        df = cls.read_raw_dataframe(file_path, max_rows=10)
        columns = [str(col).strip() for col in df.columns]
        
        # 归一化查找字典
        col_lookup = {col.lower(): col for col in columns}
        
        suggested_mapping: Dict[str, str] = {}
        matched_cols = set()

        # 1. 精确匹配（不区分大小写）：先给所有字段做精确匹配，避免模糊匹配抢走后序字段的精确列
        for std in STANDARD_FIELD_DEFINITIONS:
            std_key = std["key"]
            for alias in std["aliases"]:
                alias_lower = alias.lower()
                if alias_lower in col_lookup and col_lookup[alias_lower] not in matched_cols:
                    suggested_mapping[std_key] = col_lookup[alias_lower]
                    matched_cols.add(col_lookup[alias_lower])
                    break

        # 2. 模糊匹配：只对尚未匹配的字段做子串匹配
        for std in STANDARD_FIELD_DEFINITIONS:
            std_key = std["key"]
            if std_key in suggested_mapping:
                continue
            found_col = None
            for alias in std["aliases"]:
                alias_lower = alias.lower()
                for col_low, raw_col in col_lookup.items():
                    if raw_col in matched_cols:
                        continue
                    if alias_lower in col_low or col_low in alias_lower:
                        found_col = raw_col
                        break
                if found_col:
                    break
            if found_col:
                suggested_mapping[std_key] = found_col
                matched_cols.add(found_col)

        # 预览数据清洗
        preview_records = []
        raw_preview = df.head(5).to_dict(orient="records")
        for row in raw_preview:
            clean_row = {}
            for k, v in row.items():
                if pd.isna(v) or v is None:
                    clean_row[str(k).strip()] = ""
                else:
                    clean_row[str(k).strip()] = str(v)
            preview_records.append(clean_row)

        return {
            "columns": columns,
            "standard_fields": STANDARD_FIELD_DEFINITIONS,
            "suggested_mapping": suggested_mapping,
            "preview_data": preview_records,
            "total_sample_rows": len(df)
        }

    @classmethod
    def process_and_standardize(
        cls, 
        file_path: str, 
        field_mapping: Dict[str, str],
        coord_sys: str = "WGS-84",
        rat: str = "4G"
    ) -> pd.DataFrame:
        """
        根据字段映射处理全量表格数据，清洗为标准工参 DataFrame。
        不自动识别 4G/5G，由用户在导入时指定 rat ("4G" 或 "5G")。
        coord_sys: "WGS-84" 或 "GCJ-02" (原始文件坐标系)
        """
        df = cls.read_raw_dataframe(file_path)
        
        # 完整保留所有原始导入表头；同时为标准属性建立标准列别名以便引擎计算
        for std_key, file_col in field_mapping.items():
            if file_col in df.columns:
                df[std_key] = df[file_col]

        # 保证引擎核心计算列存在（若未映射或不存在则设置默认值）
        for std in STANDARD_FIELD_DEFINITIONS:
            if std["key"] not in df.columns:
                df[std["key"]] = ""

        # 经纬度清洗与类型转换
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
        df = df.dropna(subset=["longitude", "latitude"])
        df = df[(df["longitude"] >= 70.0) & (df["longitude"] <= 140.0) & (df["latitude"] >= 0.0) & (df["latitude"] <= 60.0)]

        # 方位角数值规范
        df["azimuth"] = pd.to_numeric(df["azimuth"], errors="coerce").fillna(0.0)
        df["azimuth"] = df["azimuth"].apply(lambda x: float(x) % 360.0 if not pd.isna(x) else 0.0)

        # 下倾角与挂高
        df["tilt"] = pd.to_numeric(df["tilt"], errors="coerce").fillna(0.0)
        df["height"] = pd.to_numeric(df["height"], errors="coerce").fillna(25.0)

        # 由用户导入后指定此次工参制式（4G 或 5G），不进行自动猜测识别
        target_rat = "5G" if str(rat).strip().upper() in ["5G", "NR", "5"] else "4G"
        df["rat"] = target_rat

        # 基站名称与小区名称默认补全（逐值处理：pandas 3.x 下 astype(str) 会保留 NaN，
        # fillna("") 对 float64 列又会在 pandas 4 报错；map + isna 对所有 dtype 都稳妥）
        df["cell_name"] = df["cell_name"].map(lambda v: "" if pd.isna(v) else str(v).strip())
        df["site_name"] = df["site_name"].map(lambda v: "" if pd.isna(v) else str(v).strip())
        df.loc[df["site_name"] == "", "site_name"] = df["cell_name"]

        # 计算双坐标（WGS-84 和 GCJ-02）
        if coord_sys.upper() == "GCJ-02":
            df["longitude_gcj"] = df["longitude"]
            df["latitude_gcj"] = df["latitude"]
            wgs_coords = [gcj02_to_wgs84(lon, lat) for lon, lat in zip(df["longitude_gcj"], df["latitude_gcj"])]
            df["longitude"] = [c[0] for c in wgs_coords]
            df["latitude"] = [c[1] for c in wgs_coords]
        else:
            gcj_coords = [wgs84_to_gcj02(lon, lat) for lon, lat in zip(df["longitude"], df["latitude"])]
            df["longitude_gcj"] = [c[0] for c in gcj_coords]
            df["latitude_gcj"] = [c[1] for c in gcj_coords]

        # 填充字符型列空值
        fill_cols = ["site_id", "cell_id", "cgi", "freq_band", "pci", "cover_type"]
        for c in fill_cols:
            df[c] = df[c].fillna("").astype(str).str.strip()

        return df
