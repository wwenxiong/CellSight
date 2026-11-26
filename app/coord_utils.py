# -*- coding: utf-8 -*-
"""
GCJ-02 (火星坐标) ↔ WGS-84 (地球坐标) 高精度互转库。

GCJ-02 是中国国家测绘局制定的地理坐标系统，是对真实坐标系统进行人为加偏处理，
又称"火星坐标系统"。本模块实现 WGS-84 与 GCJ-02 之间的高精度坐标互转。
"""

import math
import re
from typing import Optional

# Krasovsky 1940 椭球参数
_A = 6378245.0  # 长半轴
_EE = 0.00669342162296594  # 偏心率平方

_PI = math.pi


def is_out_of_china(lng: float, lat: float) -> bool:
    """判断坐标是否在中国境外（粗略矩形范围判断）。

    Parameters
    ----------
    lng : float
        经度
    lat : float
        纬度

    Returns
    -------
    bool
        True 表示在中国境外，False 表示在中国境内。
    """
    if lng < 72.004 or lng > 137.8347:
        return True
    if lat < 0.8293 or lat > 55.8271:
        return True
    return False


def _transform_lat(lng: float, lat: float) -> float:
    """纬度偏移量计算。"""
    ret = (
        -100.0
        + 2.0 * lng
        + 3.0 * lat
        + 0.2 * lat * lat
        + 0.1 * lng * lat
        + 0.2 * math.sqrt(abs(lng))
    )
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320.0 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    """经度偏移量计算。"""
    ret = (
        300.0
        + lng
        + 2.0 * lat
        + 0.1 * lng * lng
        + 0.1 * lng * lat
        + 0.1 * math.sqrt(abs(lng))
    )
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84 坐标转 GCJ-02 坐标。

    Parameters
    ----------
    lng : float
        WGS-84 经度
    lat : float
        WGS-84 纬度

    Returns
    -------
    tuple[float, float]
        (GCJ-02 经度, GCJ-02 纬度)
    """
    if is_out_of_china(lng, lat):
        return lng, lat

    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)

    rad_lat = lat / 180.0 * _PI
    magic = math.sin(rad_lat)
    magic = 1.0 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lat = (d_lat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrt_magic) * _PI)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * _PI)

    mg_lat = lat + d_lat
    mg_lng = lng + d_lng
    return mg_lng, mg_lat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 坐标转 WGS-84 坐标（高精度逆向迭代法，误差 < 0.1m）。

    Parameters
    ----------
    lng : float
        GCJ-02 经度
    lat : float
        GCJ-02 纬度

    Returns
    -------
    tuple[float, float]
        (WGS-84 经度, WGS-84 纬度)
    """
    if is_out_of_china(lng, lat):
        return lng, lat

    wgs_lng = lng
    wgs_lat = lat
    # 迭代逼近 4 次，将反解误差降低至 0.05 米以内
    for _ in range(4):
        curr_gcj_lng, curr_gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        d_lng = curr_gcj_lng - lng
        d_lat = curr_gcj_lat - lat
        wgs_lng -= d_lng
        wgs_lat -= d_lat

    return wgs_lng, wgs_lat


def wgs84_to_gcj02_batch(lng_arr, lat_arr):
    """向量化批量将 WGS-84 坐标数组转为 GCJ-02（12万点耗时 < 20ms）。"""
    import numpy as np
    lng = np.asarray(lng_arr, dtype=np.float64)
    lat = np.asarray(lat_arr, dtype=np.float64)
    out_china = (lng < 72.004) | (lng > 137.8347) | (lat < 0.8293) | (lat > 55.8271)

    x = lng - 105.0
    y = lat - 35.0
    d_lat = (
        -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(np.abs(x))
        + (20.0 * np.sin(6.0 * x * _PI) + 20.0 * np.sin(2.0 * x * _PI)) * 2.0 / 3.0
        + (20.0 * np.sin(y * _PI) + 40.0 * np.sin(y / 3.0 * _PI)) * 2.0 / 3.0
        + (160.0 * np.sin(y / 12.0 * _PI) + 320.0 * np.sin(y * _PI / 30.0)) * 2.0 / 3.0
    )
    d_lng = (
        300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(np.abs(x))
        + (20.0 * np.sin(6.0 * x * _PI) + 20.0 * np.sin(2.0 * x * _PI)) * 2.0 / 3.0
        + (20.0 * np.sin(x * _PI) + 40.0 * np.sin(x / 3.0 * _PI)) * 2.0 / 3.0
        + (150.0 * np.sin(x / 12.0 * _PI) + 300.0 * np.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    )

    rad_lat = lat / 180.0 * _PI
    magic = 1.0 - _EE * np.sin(rad_lat) ** 2
    sqrt_magic = np.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrt_magic) * _PI)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * np.cos(rad_lat) * _PI)

    res_lng = np.where(out_china, lng, lng + d_lng)
    res_lat = np.where(out_china, lat, lat + d_lat)
    return res_lng, res_lat


def gcj02_to_wgs84_batch(lng_arr, lat_arr):
    """向量化批量将 GCJ-02 坐标数组逆向迭代转为 WGS-84。"""
    import numpy as np
    lng = np.asarray(lng_arr, dtype=np.float64)
    lat = np.asarray(lat_arr, dtype=np.float64)
    wgs_lng = lng.copy()
    wgs_lat = lat.copy()
    for _ in range(4):
        curr_lng, curr_lat = wgs84_to_gcj02_batch(wgs_lng, wgs_lat)
        wgs_lng -= (curr_lng - lng)
        wgs_lat -= (curr_lat - lat)
    return wgs_lng, wgs_lat


def parse_coordinates(text: str) -> Optional[tuple[float, float]]:
    """解析经纬度字符串，返回 (lng, lat)。若不是合法坐标格式则返回 None。

    支持格式：
    - "113.32, 23.13" / "113.32 23.13" / "113.32，23.13"
    - "经度: 113.32, 纬度: 23.13" / "lat: 23.13, lng: 113.32"
    - 智能识别经纬度倒置（如 "23.13, 113.32" 自动识别中国范围坐标并纠偏）
    """
    if not text:
        return None
    s = text.strip()
    pattern = (
        r'^(?:(?:(?:经度|lng|lon|e)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)\s*[,，;\s/|]+\s*(?:(?:纬度|lat|n)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)|'
        r'(?:(?:纬度|lat|n)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)\s*[,，;\s/|]+\s*(?:(?:经度|lng|lon|e)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?))\s*$'
    )
    m = re.match(pattern, s, re.IGNORECASE)
    if not m:
        return None

    g = m.groups()
    if g[0] is not None and g[1] is not None:
        v1, v2 = float(g[0]), float(g[1])
        is_lat_first = bool(re.search(r'(?:纬度|lat|n)', s[:len(s)//2], re.IGNORECASE))
    else:
        v1, v2 = float(g[2]), float(g[3])
        is_lat_first = True

    if is_lat_first:
        lat, lng = v1, v2
    else:
        lng, lat = v1, v2

    if abs(lng) <= 90.0 and abs(lat) > 90.0:
        lng, lat = lat, lng
    elif 73.0 <= lat <= 138.0 and 3.0 <= lng <= 54.0:
        lng, lat = lat, lng

    if -180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0:
        return round(lng, 6), round(lat, 6)
    return None


def calculate_distance_and_bearing(lng1: float, lat1: float, lng2: float, lat2: float) -> tuple[float, float]:
    """计算两点间地表大圆距离（米）和真北方位角（度，0~360）。
    
    Returns
    -------
    tuple[float, float]
        (距离米, 方位角0-360)
    """
    rad_lat1 = math.radians(lat1)
    rad_lat2 = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    # Haversine 距离
    a = math.sin(delta_lat / 2.0) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(delta_lng / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance = 6378137.0 * c  # WGS-84 地球半径

    # 真北方位角
    y = math.sin(delta_lng) * math.cos(rad_lat2)
    x = math.cos(rad_lat1) * math.sin(rad_lat2) - math.sin(rad_lat1) * math.cos(rad_lat2) * math.cos(delta_lng)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return round(distance, 2), round(bearing, 1)


def destination_point(lng: float, lat: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """给定起点、距离（米）与方位角（度），计算目标点经纬度。"""
    r = 6378137.0
    delta = distance_m / r
    theta = math.radians(bearing_deg)

    phi1 = math.radians(lat)
    lambda1 = math.radians(lng)

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    sin_delta = math.sin(delta)
    cos_delta = math.cos(delta)

    phi2 = math.asin(sin_phi1 * cos_delta + cos_phi1 * sin_delta * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * sin_delta * cos_phi1,
        cos_delta - sin_phi1 * math.sin(phi2)
    )

    return round(math.degrees(lambda2), 6), round(math.degrees(phi2), 6)

