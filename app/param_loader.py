# -*- coding: utf-8 -*-
"""
工参底座加载器 - 加载 LTE/NR 基站工参 CSV 文件并提供空间查询能力。

支持功能:
- 加载多厂家格式的工参 CSV（自动识别编码，模糊匹配列名）
- 圆形区域查询（经纬度 + 半径）
- 多边形区域查询（经纬度坐标列表）
- GCJ-02 / WGS-84 坐标系自动转换
"""

import logging
import math
import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from app.coord_utils import gcj02_to_wgs84, wgs84_to_gcj02

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 标准化列名 → 各厂家可能使用的别名（中英文混合）
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, list[str]] = {
    "rat": ["制式", "网络制式", "RAT", "系统"],
    "site_id": [
        "基站编号", "基站ID", "eNodeB ID", "eNodeBID",
        "gNB ID", "gNBID", "站号", "ENODEB_ID", "GNB_ID", "站点编号",
    ],
    "site_name": [
        "基站名称", "站名", "站点名称", "eNodeB名称", "gNB名称",
        "ENODEB_NAME", "GNB_NAME",
    ],
    "cell_id": [
        "小区编号", "小区ID", "Cell ID", "CellID",
        "Local Cell ID", "LocalCellID", "CELL_ID", "LOCAL_CELL_ID", "本地小区标识",
    ],
    "cell_name": ["小区名称", "小区中文名", "小区名", "CELL_NAME"],
    "cgi": ["CGI", "ECGI", "NCGI", "E-CGI", "N-CGI", "全球小区标识"],
    "longitude": ["经度", "站址经度", "基站经度", "LON", "LONGITUDE", "lng"],
    "latitude": ["纬度", "站址纬度", "基站纬度", "LAT", "LATITUDE", "lat"],
    "freq_band": [
        "频段", "频点", "EARFCN", "NR-ARFCN", "ARFCN",
        "频率", "工作频段", "FREQ_BAND", "BAND",
    ],
    "azimuth": ["方位角", "天线方位角", "AZIMUTH", "方向角"],
    "tilt": ["下倾角", "电下倾角", "机械下倾", "TILT", "总下倾角"],
    "cover_type": ["覆盖类型", "覆盖场景", "室内外", "COVER_TYPE", "场景"],
}

# 标准输出列（保证顺序一致）
STANDARD_COLUMNS: list[str] = [
    "rat", "site_id", "site_name", "cell_id", "cell_name", "cgi",
    "longitude", "latitude", "freq_band", "azimuth", "tilt", "cover_type",
]


class ParamLoader:
    """LTE/NR 工参底座加载器。

    典型用法::

        loader = ParamLoader()
        loader.load_all(lte_path="lte.csv", nr_path="nr.csv")
        summary = loader.get_summary()
        cells = loader.query_circle(114.05, 22.55, 500)
    """

    def __init__(self) -> None:
        self.all_cells: pd.DataFrame = pd.DataFrame(columns=STANDARD_COLUMNS)
        self._load_time: Optional[str] = None

    @property
    def df_all(self) -> pd.DataFrame:
        """兼容别名，指向 all_cells。"""
        return self.all_cells

    @df_all.setter
    def df_all(self, value: pd.DataFrame) -> None:
        self.all_cells = value

    @property
    def df_lte(self) -> pd.DataFrame:
        """LTE (4G) 小区。"""
        if self.all_cells is not None and not self.all_cells.empty and "rat" in self.all_cells.columns:
            return self.all_cells[self.all_cells["rat"] == "4G"]
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    @df_lte.setter
    def df_lte(self, value: pd.DataFrame) -> None:
        pass

    @property
    def df_nr(self) -> pd.DataFrame:
        """NR (5G) 小区。"""
        if self.all_cells is not None and not self.all_cells.empty and "rat" in self.all_cells.columns:
            return self.all_cells[self.all_cells["rat"] == "5G"]
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    @df_nr.setter
    def df_nr(self, value: pd.DataFrame) -> None:
        pass

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _standardize_columns(
        df: pd.DataFrame,
        aliases: dict[str, list[str]],
    ) -> pd.DataFrame:
        """根据别名字典对 DataFrame 列做模糊匹配重命名。

        匹配规则: 去除首尾空白后，不区分大小写逐一比对。
        第一个匹配到的别名生效；同一标准列只映射一次。

        Parameters
        ----------
        df : pd.DataFrame
            原始 DataFrame。
        aliases : dict[str, list[str]]
            ``{标准列名: [别名1, 别名2, ...]}``。

        Returns
        -------
        pd.DataFrame
            列已重命名的 DataFrame（就地修改并返回）。
        """
        # 构建 反向映射: alias_lower -> standard_name
        reverse_map: dict[str, str] = {}
        for std_name, alias_list in aliases.items():
            for alias in alias_list:
                reverse_map[alias.strip().lower()] = std_name

        rename_map: dict[str, str] = {}
        already_mapped: set[str] = set()  # 一个标准列只映射一次

        for col in df.columns:
            col_key = col.strip().lower()
            if col_key in reverse_map:
                std = reverse_map[col_key]
                if std not in already_mapped:
                    rename_map[col] = std
                    already_mapped.add(std)

        if rename_map:
            df.rename(columns=rename_map, inplace=True)

        return df

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def load_csv(self, filepath: str, rat: str = "4G") -> pd.DataFrame:
        """加载单个工参 CSV 文件。

        先尝试 UTF-8 编码，失败后回退到 GBK。对列名做模糊匹配后统一为
        标准列名。缺失列填 NaN。

        Parameters
        ----------
        filepath : str
            CSV 文件路径。
        rat : str, optional
            网络制式标记，默认 ``"4G"``。若 CSV 中已有 ``rat`` 列则保留原值。

        Returns
        -------
        pd.DataFrame
            标准化后的 DataFrame。
        """
        # 1. 读取文件 —— 支持 .xlsx / .xls 或 CSV（优先 UTF-8，回退 GBK / GB18030）
        df: Optional[pd.DataFrame] = None
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".xlsx", ".xls"):
            try:
                excel_file = pd.ExcelFile(filepath)
                target_sheet = 0
                if rat:
                    rat_norm = str(rat).upper()
                    for idx, sname in enumerate(excel_file.sheet_names):
                        sn_upper = str(sname).upper()
                        if rat_norm in sn_upper or ("NR" in sn_upper if "5G" in rat_norm else False) or ("LTE" in sn_upper if "4G" in rat_norm else False):
                            target_sheet = idx
                            break
                df = pd.read_excel(excel_file, sheet_name=target_sheet, dtype=str)
                logger.info("成功读取 Excel 工参: %s (工作表: %s)", filepath, target_sheet)
            except Exception as e:
                raise ValueError(f"无法读取 Excel 工参文件: {filepath} ({e})")
        else:
            for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
                try:
                    df = pd.read_csv(filepath, encoding=encoding, dtype=str, low_memory=False)
                    logger.info("成功以 %s 编码读取: %s", encoding, filepath)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

        if df is None:
            raise ValueError(f"无法以常见编码读取文件: {filepath}")

        # 2. 列名标准化
        df = self._standardize_columns(df, COLUMN_ALIASES)

        # 3. 补充 rat 列
        if "rat" not in df.columns:
            df["rat"] = rat
        else:
            # 填充空值
            df["rat"] = df["rat"].fillna(rat)

        # 4. 确保所有标准列存在，缺失列补 NaN
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA

        # 5. 只保留标准列（加上可能存在的额外列也保留，以便调试）
        #    但至少保证标准列在前
        extra_cols = [c for c in df.columns if c not in STANDARD_COLUMNS]
        df = df[STANDARD_COLUMNS + extra_cols]

        logger.info("加载 %s 条记录 (rat=%s) from %s", len(df), rat, filepath)
        return df

    def load_all(
        self,
        lte_path: Optional[str] = None,
        nr_path: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载 LTE 和/或 NR 工参，合并后清洗坐标。

        Parameters
        ----------
        lte_path : str, optional
            LTE（4G）工参 CSV 路径。
        nr_path : str, optional
            NR（5G）工参 CSV 路径。

        Returns
        -------
        pd.DataFrame
            合并后的全量小区 DataFrame（存储在 ``self.all_cells``）。
        """
        frames: list[pd.DataFrame] = []

        if lte_path:
            frames.append(self.load_csv(lte_path, rat="4G"))
        if nr_path:
            frames.append(self.load_csv(nr_path, rat="5G"))

        if not frames:
            logger.warning("未提供任何工参文件路径，all_cells 为空。")
            self.all_cells = pd.DataFrame(columns=STANDARD_COLUMNS)
            self._load_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return self.all_cells

        df = pd.concat(frames, ignore_index=True)

        # 将经纬度转为数值型，不可转换的变为 NaN
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")

        # 丢弃经纬度无效的行
        before = len(df)
        df.dropna(subset=["longitude", "latitude"], inplace=True)
        df.reset_index(drop=True, inplace=True)
        dropped = before - len(df)
        if dropped:
            logger.warning("因经纬度无效丢弃 %d 条记录。", dropped)

        self.all_cells = df
        self._load_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("合并完成: 共 %d 条小区记录。", len(df))
        return self.all_cells

    def get_summary(self) -> dict:
        """返回当前工参数据的统计摘要。

        Returns
        -------
        dict
            包含更新时间、站点数、小区数、制式分布、频段分布等信息。
        """
        df = self.all_cells

        # 计算中心代表坐标（采用中位数提取工参核心集中区域）
        center_lng, center_lat = 113.33, 23.13
        if not df.empty and "longitude" in df.columns and "latitude" in df.columns:
            vlng = df["longitude"].dropna()
            vlat = df["latitude"].dropna()
            if not vlng.empty and not vlat.empty:
                center_lng = float(vlng.median())
                center_lat = float(vlat.median())

        gcj_lng, gcj_lat = wgs84_to_gcj02(center_lng, center_lat)

        # 站点去重（以 site_id 为准，若无则退化为按 site_name）
        if "site_id" in df.columns and df["site_id"].notna().any():
            total_sites = int(df["site_id"].nunique())
        else:
            total_sites = int(df["site_name"].nunique()) if "site_name" in df.columns else 0

        lte_mask = df["rat"].astype(str).str.upper().isin(["4G", "LTE"])
        nr_mask = df["rat"].astype(str).str.upper().isin(["5G", "NR"])

        # 频段分布
        freq_bands: dict[str, int] = {}
        if "freq_band" in df.columns:
            freq_counts = df["freq_band"].dropna().astype(str).value_counts()
            freq_bands = freq_counts.to_dict()

        return {
            "update_time": self._load_time or "",
            "total_sites": total_sites,
            "total_cells": len(df),
            "lte_cells": int(lte_mask.sum()),
            "nr_cells": int(nr_mask.sum()),
            "freq_bands": freq_bands,
            "center_lng": round(center_lng, 4),
            "center_lat": round(center_lat, 4),
            "center_lng_wgs": round(center_lng, 6),
            "center_lat_wgs": round(center_lat, 6),
            "center_lng_gcj": round(gcj_lng, 6),
            "center_lat_gcj": round(gcj_lat, 6),
        }

    def query_circle(
        self,
        center_lng: float,
        center_lat: float,
        radius_m: float,
        coord_sys: str = "wgs84",
    ) -> pd.DataFrame:
        """圆形区域精准测地线查询 —— 返回圆心半径范围内的所有小区。
        使用标准 Haversine 地球大圆距离算法，消除纬度拉伸形变，米级精度。

        Parameters
        ----------
        center_lng : float
            圆心经度。
        center_lat : float
            圆心纬度。
        radius_m : float
            半径（米）。
        coord_sys : str, optional
            输入坐标系，``"wgs84"`` 或 ``"gcj02"``，默认 ``"wgs84"``。
            若为 ``"gcj02"``，会先将圆心高精度转为真实 WGS-84 坐标。

        Returns
        -------
        pd.DataFrame
            在圆形范围内的小区子集。
        """
        if coord_sys.lower() == "gcj02":
            center_lng, center_lat = gcj02_to_wgs84(center_lng, center_lat)

        df = self.all_cells
        if df.empty:
            return df.copy()

        # 使用精确的地球大圆距离 (Haversine 算法)
        r_earth = 6371000.0  # 地球平均半径(米)
        phi1 = math.radians(center_lat)
        phi2 = np.radians(df["latitude"].values)
        dphi = np.radians(df["latitude"].values - center_lat)
        dlambda = np.radians(df["longitude"].values - center_lng)

        a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * (np.sin(dlambda / 2.0) ** 2)
        c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        distances = r_earth * c

        mask = distances <= radius_m
        result = df.loc[mask].copy()
        result["distance_m"] = np.round(distances[mask], 1)
        result.sort_values(by="distance_m", inplace=True)
        return result.reset_index(drop=True)

    def query_polygon(
        self,
        polygon_coords: list[list[float]],
        coord_sys: str = "wgs84",
    ) -> pd.DataFrame:
        """多边形区域查询 —— 返回多边形内的所有小区。

        Parameters
        ----------
        polygon_coords : list[list[float]]
            多边形顶点坐标列表 ``[[lng, lat], ...]``。
        coord_sys : str, optional
            输入坐标系，``"wgs84"`` 或 ``"gcj02"``，默认 ``"wgs84"``。
            若为 ``"gcj02"``，会先将所有顶点转为 WGS-84。

        Returns
        -------
        pd.DataFrame
            在多边形范围内的小区子集。
        """
        df = self.all_cells
        if df.empty:
            return df.copy()

        # 过滤非法点
        valid_coords = []
        for pt in polygon_coords:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    lng, lat = float(pt[0]), float(pt[1])
                    if not (math.isnan(lng) or math.isnan(lat) or math.isinf(lng) or math.isinf(lat)):
                        valid_coords.append([lng, lat])
                except (ValueError, TypeError):
                    continue

        if len(valid_coords) < 3:
            return df.iloc[0:0].copy().reset_index(drop=True)

        if coord_sys.lower() == "gcj02":
            valid_coords = [
                list(gcj02_to_wgs84(pt[0], pt[1])) for pt in valid_coords
            ]

        # 构建 Shapely Polygon
        try:
            poly = Polygon([(pt[0], pt[1]) for pt in valid_coords])
            if not poly.is_valid:
                poly = make_valid(poly)
        except Exception as e:
            logger.warning("多边形几何构造异常: %s", e)
            return df.iloc[0:0].copy().reset_index(drop=True)

        # 空间包围盒 (BBox) 极速初筛，将 3万+ 小区快速过滤到包围盒内
        try:
            min_lng, min_lat, max_lng, max_lat = poly.bounds
            df_box = df[
                (df["longitude"] >= min_lng)
                & (df["longitude"] <= max_lng)
                & (df["latitude"] >= min_lat)
                & (df["latitude"] <= max_lat)
            ]
            if df_box.empty:
                return df_box.copy().reset_index(drop=True)

            mask = df_box.apply(
                lambda row: Point(row["longitude"], row["latitude"]).within(poly),
                axis=1,
            )
            return df_box.loc[mask].copy().reset_index(drop=True)
        except Exception as e:
            logger.error("多边形空间匹配异常: %s", e)
            return df.iloc[0:0].copy().reset_index(drop=True)

    def query_multipolygon(
        self,
        polygons_coords: list[list[list[float]]],
        coord_sys: str = "wgs84",
    ) -> pd.DataFrame:
        """多个多边形联合区域查询 —— 返回落入任意一个多边形内的小区。

        Parameters
        ----------
        polygons_coords : list[list[list[float]]]
            多个多边形顶点坐标列表 ``[[[lng, lat], ...], ...]``。
        coord_sys : str, optional
            输入坐标系，``"wgs84"`` 或 ``"gcj02"``，默认 ``"wgs84"``。

        Returns
        -------
        pd.DataFrame
            落入任意多边形范围内的小区子集。
        """
        df = self.all_cells
        if df.empty or not polygons_coords:
            return df.iloc[0:0].copy().reset_index(drop=True)

        valid_polys = []
        for poly_coords in polygons_coords:
            valid_pts = []
            for pt in poly_coords:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    try:
                        lng, lat = float(pt[0]), float(pt[1])
                        if not (math.isnan(lng) or math.isnan(lat) or math.isinf(lng) or math.isinf(lat)):
                            valid_pts.append([lng, lat])
                    except (ValueError, TypeError):
                        continue
            if len(valid_pts) < 3:
                continue

            if coord_sys.lower() == "gcj02":
                valid_pts = [list(gcj02_to_wgs84(p[0], p[1])) for p in valid_pts]

            try:
                p = Polygon([(pt[0], pt[1]) for pt in valid_pts])
                if not p.is_valid:
                    p = make_valid(p)
                if not p.is_empty:
                    valid_polys.append(p)
            except Exception:
                continue

        if not valid_polys:
            return df.iloc[0:0].copy().reset_index(drop=True)

        try:
            combined = unary_union(valid_polys)
            min_lng, min_lat, max_lng, max_lat = combined.bounds
            df_box = df[
                (df["longitude"] >= min_lng)
                & (df["longitude"] <= max_lng)
                & (df["latitude"] >= min_lat)
                & (df["latitude"] <= max_lat)
            ]
            if df_box.empty:
                return df_box.copy().reset_index(drop=True)

            mask = df_box.apply(
                lambda row: Point(row["longitude"], row["latitude"]).within(combined),
                axis=1,
            )
            return df_box.loc[mask].copy().reset_index(drop=True)
        except Exception as e:
            logger.error("组合多边形空间匹配异常: %s", e)
            return df.iloc[0:0].copy().reset_index(drop=True)
