# -*- coding: utf-8 -*-
"""
PCI 冲突与混淆检测引擎 - 快速发现同频同PCI与邻区同频同PCI干扰
"""

import math
from typing import List, Dict, Any
from app.coord_utils import calculate_distance_and_bearing

def check_pci_conflicts(cells: List[Dict[str, Any]], distance_threshold_m: float = 6000.0) -> Dict[str, Any]:
    """
    针对输入的小区集合，检测同频同PCI冲突
    distance_threshold_m: 冲突距离门限（默认 6km 范围内视为潜在严重冲突）
    """
    conflicts = []
    
    # 建立 (rat, freq_band, pci) 索引桶
    buckets = {}
    valid_cells = []
    
    for c in cells:
        pci_val = str(c.get("pci", "")).strip()
        if not pci_val or pci_val == "0" or pci_val == "-":
            continue
        try:
            lat = float(c.get("latitude", 0))
            lon = float(c.get("longitude", 0))
        except (ValueError, TypeError):
            continue
            
        if lat == 0 or lon == 0:
            continue
            
        rat = str(c.get("rat", "4G")).upper()
        band = str(c.get("freq_band", "")).strip().upper()
        # 归一化频段/频点
        key = f"{rat}_{band}_{pci_val}"
        
        c_info = {
            "cell_name": c.get("cell_name", ""),
            "site_name": c.get("site_name", ""),
            "cgi": c.get("cgi", ""),
            "pci": pci_val,
            "rat": rat,
            "freq_band": band,
            "longitude": lon,
            "latitude": lat,
            "longitude_gcj": c.get("longitude_gcj", lon),
            "latitude_gcj": c.get("latitude_gcj", lat),
            "azimuth": c.get("azimuth", 0)
        }
        
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(c_info)

    # 桶内双重循环测距比较
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        n = len(group)
        for i in range(n):
            for j in range(i + 1, n):
                c1 = group[i]
                c2 = group[j]
                # 排除同一物理基站内部不同扇区同频同PCI的情形（极罕见或配置错误）
                dist, bearing = calculate_distance_and_bearing(
                    c1["longitude"], c1["latitude"],
                    c2["longitude"], c2["latitude"]
                )
                if dist <= distance_threshold_m:
                    conflicts.append({
                        "type": "同频同PCI冲突",
                        "severity": "严重" if dist < 3000 else "中度",
                        "distance_m": round(dist, 1),
                        "bearing_deg": bearing,
                        "pci": c1["pci"],
                        "freq_band": c1["freq_band"],
                        "rat": c1["rat"],
                        "cell_a": c1,
                        "cell_b": c2
                    })

    # 按距离从近到远排序
    conflicts.sort(key=lambda x: x["distance_m"])

    return {
        "total_conflicts": len(conflicts),
        "conflicts": conflicts
    }
