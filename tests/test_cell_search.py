# -*- coding: utf-8 -*-
"""全局工参模糊检索功能单元测试。

验证：
1. CellDB.search_cells 单关键字与空格分词多关键字组合查询（AND 模糊匹配）
2. 制式过滤 (ALL / 4G / 5G) 与分页 (limit / offset)
3. /api/cells/search FastAPI 接口响应与 GCJ-02 坐标自动补齐
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.cell_db import CellDB
from main import app


def _sample_df():
    return pd.DataFrame([
        {
            "cell_name": "九龙坡隆鑫C区-5G-1",
            "site_name": "九龙坡隆鑫C区",
            "site_id": "10107827",
            "cell_id": "384",
            "pci": "831",
            "tac": "9792512",
            "freq_band": "3.5G",
            "rat": "5G",
            "is_shared": "是",
            "ul_earfcn": "636664",
            "dl_earfcn": "636664",
            "longitude": 106.344166,
            "latitude": 29.417256,
            "layer_name": "5G工参",
        },
        {
            "cell_name": "九龙坡隆鑫C区-4G-1",
            "site_name": "九龙坡隆鑫C区",
            "site_id": "20107827",
            "cell_id": "12",
            "pci": "105",
            "tac": "12345",
            "freq_band": "1.8G",
            "rat": "4G",
            "is_shared": "否",
            "ul_earfcn": "1825",
            "dl_earfcn": "1825",
            "longitude": 106.3442,
            "latitude": 29.4173,
            "layer_name": "4G工参",
        },
        {
            "cell_name": "南坪万达广场-4G-2",
            "site_name": "南坪万达广场",
            "site_id": "30109999",
            "cell_id": "22",
            "pci": "208",
            "tac": "54321",
            "freq_band": "2.1G",
            "rat": "4G",
            "is_shared": "是",
            "ul_earfcn": "100",
            "dl_earfcn": "100",
            "longitude": 106.571,
            "latitude": 29.528,
            "layer_name": "4G工参",
        },
    ])


def test_cell_db_search_fuzzy_and_multi_tokens(tmp_path):
    db_path = tmp_path / "search_test.db"
    CellDB.save_dataframe(_sample_df(), db_path=db_path)

    # 1. 单关键字模糊查询（PCI）
    res_pci = CellDB.search_cells(query="831", db_path=db_path)
    assert res_pci["total"] == 1
    assert res_pci["cells"][0]["cell_name"] == "九龙坡隆鑫C区-5G-1"

    # 2. 空格分词多关键字 AND 查询（基站名 + 频段）
    res_multi = CellDB.search_cells(query="隆鑫 1.8G", db_path=db_path)
    assert res_multi["total"] == 1
    assert res_multi["cells"][0]["cell_id"] == "12"

    # 3. 制式过滤与分页
    res_4g = CellDB.search_cells(query="", rat="4G", limit=1, offset=1, db_path=db_path)
    assert res_4g["total"] == 2
    assert len(res_4g["cells"]) == 1


def test_api_cells_search_endpoint(tmp_path, monkeypatch):
    db_path = tmp_path / "api_search_test.db"
    CellDB.save_dataframe(_sample_df(), db_path=db_path)
    monkeypatch.setattr("app.cell_db.DEFAULT_DB_PATH", db_path)

    client = TestClient(app)
    resp = client.get("/api/cells/search", params={"q": "万达 208", "rat": "ALL"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["cells"]) == 1
    cell = data["cells"][0]
    assert cell["site_name"] == "南坪万达广场"
    assert cell["longitude_gcj"] is not None
    assert cell["latitude_gcj"] is not None


def test_cell_search_layer_filtering(tmp_path, monkeypatch):
    """测试单图层与多图层精确过滤检索。"""
    db_path = tmp_path / "layer_search_test.db"
    CellDB.save_dataframe(_sample_df(), db_path=db_path)
    monkeypatch.setattr("app.cell_db.DEFAULT_DB_PATH", db_path)

    # 1. 仅从 5G工参 中搜索「隆鑫」
    res_5g = CellDB.search_cells(query="隆鑫", layers=["5G工参"], db_path=db_path)
    assert res_5g["total"] == 1
    assert res_5g["cells"][0]["layer_name"] == "5G工参"

    # 2. 仅从 4G工参 中搜索「隆鑫」
    res_4g = CellDB.search_cells(query="隆鑫", layers=["4G工参"], db_path=db_path)
    assert res_4g["total"] == 1
    assert res_4g["cells"][0]["layer_name"] == "4G工参"

    # 3. 通过 API 传入多个图层过滤
    client = TestClient(app)
    resp = client.get("/api/cells/search", params={"q": "隆鑫", "layers": "4G工参,5G工参"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

