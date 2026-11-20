# -*- coding: utf-8 -*-
"""
经纬度边界与保障区域文件解析模块。

支持解析：
1. 包含活动名称、起止时间及多个“事件区域 / 经纬度范围”的通信保障文本文件（如微信发送的通知或导出配置）；
2. 标准 GeoJSON 文件（FeatureCollection / Feature / Polygon / MultiPolygon）；
3. 纯经纬度坐标点串或数组。
"""

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from app.coord_utils import gcj02_to_wgs84, wgs84_to_gcj02


def _clean_coordinate_pair(pt: Any) -> Optional[Tuple[float, float]]:
    """清洗单组经纬度点，保证 lng, lat 均为合法浮点数。
    自动识别经度(70~140)与纬度(0~60)顺序，若颠倒则自动纠正。
    """
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return None
    try:
        x = float(pt[0])
        y = float(pt[1])
    except (ValueError, TypeError):
        return None

    if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
        return None

    # 中国境内经纬度自动纠偏判断 (经度大约 73~136, 纬度大约 3~54)
    # 如果 x 在 0~60 之间而 y 在 70~140 之间，说明是 [lat, lng]，自动交换为 [lng, lat]
    if (0.0 <= x <= 65.0) and (70.0 <= y <= 140.0):
        return (round(y, 7), round(x, 7))

    return (round(x, 7), round(y, 7))


def _clean_coordinates_list(coords: List[Any]) -> List[List[float]]:
    """清洗一组多边形坐标列表，过滤非法点并保证至少3个有效点。"""
    cleaned: List[List[float]] = []
    for p in coords:
        pair = _clean_coordinate_pair(p)
        if pair is not None:
            cleaned.append([pair[0], pair[1]])

    # 若首尾闭合点重复，在做多边形顶点的统一表达时保留或兼容
    if len(cleaned) >= 3:
        return cleaned
    return []


def _extract_coords_from_geojson(geom: Dict[str, Any]) -> List[List[List[float]]]:
    """从 GeoJSON 几何体中提取多边形坐标列表。
    返回一个或多个多边形环坐标 [[ [lng, lat], ... ], ...]
    """
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    results: List[List[List[float]]] = []

    if gtype == "Polygon":
        if isinstance(coords, list) and len(coords) > 0:
            ring = coords[0]
            clean_ring = _clean_coordinates_list(ring)
            if len(clean_ring) >= 3:
                results.append(clean_ring)
    elif gtype == "MultiPolygon":
        if isinstance(coords, list):
            for poly in coords:
                if isinstance(poly, list) and len(poly) > 0:
                    clean_ring = _clean_coordinates_list(poly[0])
                    if len(clean_ring) >= 3:
                        results.append(clean_ring)
    elif isinstance(coords, list):
        # 兜底：尝试展平
        clean_ring = _clean_coordinates_list(coords)
        if len(clean_ring) >= 3:
            results.append(clean_ring)

    return results


def _build_region_dict(name: str, coords: List[List[float]], coord_sys: str = "wgs84") -> Dict[str, Any]:
    """构建标准区域对象，计算中心点与 GCJ-02 / WGS-84 坐标映射。"""
    if coord_sys.lower() == "gcj02":
        coords_gcj = coords
        coords_wgs = [[round(w[0], 7), round(w[1], 7)] for w in [gcj02_to_wgs84(p[0], p[1]) for p in coords]]
    else:
        coords_wgs = coords
        coords_gcj = [[round(g[0], 7), round(g[1], 7)] for g in [wgs84_to_gcj02(p[0], p[1]) for p in coords]]

    c_lng = sum(p[0] for p in coords) / len(coords)
    c_lat = sum(p[1] for p in coords) / len(coords)
    cg_lng = sum(p[0] for p in coords_gcj) / len(coords_gcj)
    cg_lat = sum(p[1] for p in coords_gcj) / len(coords_gcj)

    return {
        "name": name,
        "coords": coords,
        "coords_wgs": coords_wgs,
        "coords_gcj": coords_gcj,
        "center": [round(c_lng, 6), round(c_lat, 6)],
        "center_gcj": [round(cg_lng, 6), round(cg_lat, 6)],
        "points_count": len(coords),
        "bounds": [
            [min(p[1] for p in coords_gcj), min(p[0] for p in coords_gcj)],
            [max(p[1] for p in coords_gcj), max(p[0] for p in coords_gcj)],
        ],
    }


def parse_boundary_content(content: str, coord_sys: str = "wgs84") -> Dict[str, Any]:
    """核心解析函数：解析文本内容中的保障活动、起止时间与所有事件区域多边形边界。

    Parameters
    ----------
    content : str
        文件内容或粘贴文本字符串

    Returns
    -------
    dict
        包含 activity_name, start_time, end_time, total_regions, regions: [...]
    """
    content = (content or "").strip()
    if not content:
        return {
            "activity_name": "",
            "start_time": "",
            "end_time": "",
            "total_regions": 0,
            "regions": [],
        }

    activity_name = ""
    start_time = ""
    end_time = ""

    # 1. 尝试匹配活动名称
    m_name = re.search(
        r"(?:通信保障活动名称|活动名称|保障任务名称|任务名称|活动|保障名称)[：:]\s*([^\r\n]+)",
        content,
        re.IGNORECASE,
    )
    if m_name:
        activity_name = m_name.group(1).strip()

    # 2. 尝试匹配开始时间
    m_start = re.search(
        r"(?:保障开始时间|开始时间|起始时间)[：:]\s*([^\r\n]+)",
        content,
        re.IGNORECASE,
    )
    if m_start:
        start_time = m_start.group(1).strip()

    # 3. 尝试匹配结束时间
    m_end = re.search(
        r"(?:保障结束时间|结束时间|截止时间)[：:]\s*([^\r\n]+)",
        content,
        re.IGNORECASE,
    )
    if m_end:
        end_time = m_end.group(1).strip()

    regions: List[Dict[str, Any]] = []

    # 4. 优先尝试：通信保障文本分块解析
    # 格式特征：
    # 事件区域：重庆悦来国际会议中心
    # 经纬度范围：{"type":"Polygon","coordinates":[[[106.5357,29.7210],...]]]}
    area_pattern = re.compile(
        r"(?:事件区域|保障区域|区域名称|区域)[：:]\s*([^\r\n]+)[\r\n]+"
        r"(?:经纬度范围|经纬度|坐标范围|范围)[：:]\s*(\{[\s\S]*?\}|\[[\s\S]*?\])",
        re.MULTILINE,
    )

    matches = list(area_pattern.finditer(content))
    if matches:
        for idx, m in enumerate(matches, start=1):
            name = m.group(1).strip() or f"保障区域 {idx}"
            raw_geom_str = m.group(2).strip()

            try:
                geom_data = json.loads(raw_geom_str)
                coords_list: List[List[List[float]]] = []
                if isinstance(geom_data, dict):
                    coords_list = _extract_coords_from_geojson(geom_data)
                elif isinstance(geom_data, list):
                    # 检查是否嵌套在环内 [[[lng, lat], ...]]
                    if len(geom_data) > 0 and isinstance(geom_data[0], list) and len(geom_data[0]) > 0 and isinstance(geom_data[0][0], list):
                        coords_list = _extract_coords_from_geojson({"type": "Polygon", "coordinates": geom_data})
                    else:
                        c_ring = _clean_coordinates_list(geom_data)
                        if len(c_ring) >= 3:
                            coords_list.append(c_ring)

                for r_coords in coords_list:
                    regions.append(_build_region_dict(name, r_coords, coord_sys))
            except Exception:
                continue

    # 5. 若未匹配到文本分块，尝试整篇当作 JSON 或 GeoJSON 解析
    if not regions:
        try:
            parsed_json = json.loads(content)
            if isinstance(parsed_json, dict):
                # FeatureCollection
                if parsed_json.get("type") == "FeatureCollection" and "features" in parsed_json:
                    features = parsed_json.get("features", [])
                    for idx, feat in enumerate(features, start=1):
                        props = feat.get("properties") or {}
                        feat_name = (
                            props.get("name")
                            or props.get("title")
                            or props.get("area")
                            or props.get("区域")
                            or f"区域 {idx}"
                        )
                        geom = feat.get("geometry") or feat
                        for r_coords in _extract_coords_from_geojson(geom):
                            regions.append(_build_region_dict(feat_name, r_coords, coord_sys))
                elif parsed_json.get("type") in ("Polygon", "MultiPolygon") or "coordinates" in parsed_json:
                    feat_name = activity_name or "导入多边形区域"
                    for r_coords in _extract_coords_from_geojson(parsed_json):
                        regions.append(_build_region_dict(feat_name, r_coords, coord_sys))
            elif isinstance(parsed_json, list):
                # 直接是坐标点列表 [[lng,lat], ...]
                c_ring = _clean_coordinates_list(parsed_json)
                if len(c_ring) >= 3:
                    regions.append(_build_region_dict(activity_name or "导入多边形区域", c_ring, coord_sys))
        except Exception:
            pass

    # 6. 兜底尝试：从文本中提取任意类似 {"type":"Polygon"...} 的孤立 JSON 块
    if not regions:
        json_matches = re.findall(r"(\{(?:[^{}]|(?R))*\})", content)
        for idx, j_str in enumerate(json_matches, start=1):
            try:
                j_obj = json.loads(j_str)
                if isinstance(j_obj, dict) and ("coordinates" in j_obj or j_obj.get("type") == "Polygon"):
                    extracted = _extract_coords_from_geojson(j_obj)
                    for r_coords in extracted:
                        regions.append(_build_region_dict(f"区域 {idx}", r_coords, coord_sys))
            except Exception:
                continue

    return {
        "activity_name": activity_name,
        "start_time": start_time,
        "end_time": end_time,
        "total_regions": len(regions),
        "regions": regions,
    }
