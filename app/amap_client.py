# -*- coding: utf-8 -*-
"""
高德开放平台 Web 服务 API 客户端
提供 API Key 有效性校验、POI 关键字搜索、详细地址地理编码以及逆地理编码推断城市
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Optional, Tuple, List, Dict, Any

from app.coord_utils import gcj02_to_wgs84, wgs84_to_gcj02

logger = logging.getLogger("amap_client")

# 城市坐标边界启发式映射（在无网络/无Key时作为工参推测兜底）
CITY_BOUNDS = [
    ("广州市", (112.9, 22.5, 114.1, 23.9)),
    ("深圳市", (113.7, 22.4, 114.6, 22.9)),
    ("东莞市", (113.5, 22.6, 114.3, 23.2)),
    ("佛山市", (112.6, 22.6, 113.3, 23.3)),
    ("北京市", (115.4, 39.4, 117.5, 41.1)),
    ("上海市", (120.8, 30.7, 122.2, 31.9)),
    ("杭州市", (118.3, 29.2, 120.7, 30.6)),
    ("南京市", (118.3, 31.2, 119.3, 32.6)),
    ("武汉市", (113.7, 29.9, 115.1, 31.4)),
    ("成都市", (102.9, 30.1, 104.9, 31.4)),
    ("重庆市", (105.3, 28.2, 110.2, 32.2)),
    ("西安市", (107.7, 33.7, 109.8, 34.7)),
    ("天津市", (116.7, 38.6, 118.1, 40.3)),
    ("苏州市", (120.0, 30.8, 121.4, 31.9)),
    ("长沙市", (111.9, 27.9, 114.3, 28.7)),
]


class AmapClient:
    """高德 Web 服务 API 客户端封装"""

    BASE_URL = "https://restapi.amap.com"

    def __init__(self, api_key: str = "", default_city: str = ""):
        self.api_key = api_key.strip()
        self.default_city = default_city.strip()

    def set_config(self, api_key: str, default_city: str = ""):
        self.api_key = api_key.strip()
        if default_city:
            self.default_city = default_city.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def test_key(self, api_key: Optional[str] = None) -> Tuple[bool, str]:
        """测试指定或当前 Key 的有效性"""
        key = (api_key or self.api_key).strip()
        if not key:
            return False, "尚未提供 API Key"

        url = f"{self.BASE_URL}/v3/geocode/geo?" + urllib.parse.urlencode({
            "address": "北京市天安门",
            "key": key
        })

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EmergencyWirelessAssurance/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status = data.get("status")
                info = data.get("info", "")
                infocode = data.get("infocode", "")

                if status == "1":
                    return True, "Key 验证通过，高德 Web 服务已连接"
                
                # 常见高德错误码解释
                err_map = {
                    "10001": "Key 不正确或已被删除",
                    "10002": "没有权限使用该服务，请确认创建 Key 时【服务平台】勾选了【Web服务】而非【Web端(JS API)】",
                    "10003": "该 Key 当日调用配额已超限",
                    "10004": "访问过于频繁（超并发）",
                    "10008": "绑定的 IP/域名不合法",
                }
                detail = err_map.get(infocode, f"高德返回异常: {info} (代码: {infocode})")
                return False, detail
        except Exception as e:
            return False, f"网络请求失败: {str(e)}"

    def search_poi(self, keyword: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """使用高德 Place Text API 搜索关键词 POI"""
        if not self.is_configured():
            return []

        search_city = city or self.default_city or ""
        params = {
            "keywords": keyword.strip(),
            "key": self.api_key,
            "offset": "10",
            "page": "1",
            "extensions": "all"
        }
        if search_city:
            params["city"] = search_city
            params["citylimit"] = "false"  # 优先本市，但不硬性限制

        url = f"{self.BASE_URL}/v3/place/text?" + urllib.parse.urlencode(params)
        results = []

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EmergencyWirelessAssurance/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "1" and "pois" in data:
                    for poi in data["pois"]:
                        loc = poi.get("location", "")
                        if not loc or "," not in loc:
                            continue
                        lng_str, lat_str = loc.split(",")
                        lng_gcj = float(lng_str)
                        lat_gcj = float(lat_str)
                        lng_wgs, lat_wgs = gcj02_to_wgs84(lng_gcj, lat_gcj)

                        addr = poi.get("address")
                        pname = poi.get("pname", "")
                        cityname = poi.get("cityname", "")
                        adname = poi.get("adname", "")
                        full_addr = f"{pname}{cityname}{adname} {addr}" if addr else f"{pname}{cityname}{adname}"

                        results.append({
                            "name": poi.get("name", keyword),
                            "address": full_addr.strip(),
                            "district": f"{cityname} {adname}".strip(),
                            "lng_gcj": lng_gcj,
                            "lat_gcj": lat_gcj,
                            "lng_wgs": lng_wgs,
                            "lat_wgs": lat_wgs,
                            "source": "高德精准POI",
                            "type": "amap_poi",
                        })
        except Exception as e:
            logger.warning("高德 POI 检索异常: %s", e)

        return results

    def geocode(self, address: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """使用高德 Geocode API 解析具体结构化地址"""
        if not self.is_configured():
            return []

        search_city = city or self.default_city or ""
        params = {
            "address": address.strip(),
            "key": self.api_key
        }
        if search_city:
            params["city"] = search_city

        url = f"{self.BASE_URL}/v3/geocode/geo?" + urllib.parse.urlencode(params)
        results = []

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EmergencyWirelessAssurance/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "1" and "geocodes" in data:
                    for item in data["geocodes"]:
                        loc = item.get("location", "")
                        if not loc or "," not in loc:
                            continue
                        lng_str, lat_str = loc.split(",")
                        lng_gcj = float(lng_str)
                        lat_gcj = float(lat_str)
                        lng_wgs, lat_wgs = gcj02_to_wgs84(lng_gcj, lat_gcj)

                        results.append({
                            "name": item.get("formatted_address", address),
                            "address": item.get("formatted_address", address),
                            "district": f"{item.get('province', '')} {item.get('city', '')} {item.get('district', '')}".strip(),
                            "lng_gcj": lng_gcj,
                            "lat_gcj": lat_gcj,
                            "lng_wgs": lng_wgs,
                            "lat_wgs": lat_wgs,
                            "source": "高德地理编码",
                            "type": "amap_geocode",
                        })
        except Exception as e:
            logger.warning("高德地理编码异常: %s", e)

        return results

    def reverse_geocode_city(self, lng: float, lat: float, is_wgs84: bool = True) -> str:
        """根据经纬度逆地理编码识别城市名称"""
        if not self.is_configured():
            return self.infer_city_by_coords(lng, lat)

        # 高德 regeo 需要 GCJ-02 坐标
        if is_wgs84:
            lng_gcj, lat_gcj = wgs84_to_gcj02(lng, lat)
        else:
            lng_gcj, lat_gcj = lng, lat

        url = f"{self.BASE_URL}/v3/geocode/regeo?" + urllib.parse.urlencode({
            "location": f"{lng_gcj:.6f},{lat_gcj:.6f}",
            "key": self.api_key,
            "extensions": "base"
        })

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EmergencyWirelessAssurance/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "1":
                    comp = data.get("regeocode", {}).get("addressComponent", {})
                    city = comp.get("city")
                    if isinstance(city, str) and city:
                        return city
                    province = comp.get("province")
                    if isinstance(province, str) and province:
                        return province
        except Exception as e:
            logger.warning("高德逆地理编码识别城市失败: %s", e)

        return self.infer_city_by_coords(lng, lat)

    @staticmethod
    def infer_city_by_coords(lng: float, lat: float) -> str:
        """根据坐标边界启发式匹配大致城市"""
        for city_name, (min_lng, min_lat, max_lng, max_lat) in CITY_BOUNDS:
            if min_lng <= lng <= max_lng and min_lat <= lat <= max_lat:
                return city_name
        return "广州市"  # 默认回退
