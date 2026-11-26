# -*- coding: utf-8 -*-
"""开机纯净工作台模式（方案 1）单元测试。

验证：
1. 默认开机请求 /api/params/status 不主动下发 cells 数据，确保纯净工作台轻量启动；
2. 在工参底库存在但未载入工程时，返回 loaded=False 及物理底座统计元数据；
3. 仅在显式请求 include_cells=True 且会话已载入时才返回 cells。
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
from main import app, session_state, param_loader
from app.cell_db import CellDB


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_session():
    old_state = dict(session_state)
    session_state["params_loaded"] = False
    session_state["param_summary"] = {"loaded": False, "total_sites": 0, "total_cells": 0, "lte_cells": 0, "nr_cells": 0}
    session_state["selected_cells"] = None
    old_cells = param_loader.all_cells
    old_df_all = param_loader.df_all
    yield
    session_state.clear()
    session_state.update(old_state)
    param_loader.all_cells = old_cells
    param_loader.df_all = old_df_all


def test_param_status_clean_startup_no_cells(client, tmp_path, monkeypatch, clean_session):
    """测试开机纯净状态下，/api/params/status 不下发 cells"""
    test_db = tmp_path / "test_cells.db"
    df = pd.DataFrame([
        {"cell_name": "小区1", "site_name": "基站1", "longitude": 107.5, "latitude": 29.7, "rat": "4G", "layer_name": "4G工参"},
        {"cell_name": "小区2", "site_name": "基站2", "longitude": 107.6, "latitude": 29.8, "rat": "5G", "layer_name": "5G工参"},
    ])
    CellDB.save_dataframe(df, db_path=test_db)
    monkeypatch.setattr("app.cell_db.DEFAULT_DB_PATH", test_db)

    resp = client.get("/api/params/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is False
    assert "cells" not in data
    assert data["total_cells"] == 2
    assert data["total_sites"] == 2


def test_param_status_with_loaded_session_default_no_cells(client, clean_session):
    """测试即便会话已载入工参，默认 /api/params/status 也不携带全量 cells（需主动 include_cells=True）"""
    df = pd.DataFrame([
        {"cell_name": "小区A", "site_name": "基站A", "longitude": 107.5, "latitude": 29.7, "rat": "4G", "layer_name": "4G工参"},
    ])
    param_loader.all_cells = df
    param_loader.df_all = df
    session_state["params_loaded"] = True
    session_state["param_summary"] = param_loader.get_summary()

    # 默认不携带
    resp = client.get("/api/params/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is True
    assert "cells" not in data

    # 显式 include_cells=true 才下发
    resp_with_cells = client.get("/api/params/status?include_cells=true")
    assert resp_with_cells.status_code == 200
    data_with_cells = resp_with_cells.json()
    assert data_with_cells["loaded"] is True
    assert "cells" in data_with_cells
    assert len(data_with_cells["cells"]) == 1
