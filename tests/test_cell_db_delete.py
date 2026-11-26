# -*- coding: utf-8 -*-
"""工参图层删除与清空功能单元测试。

验证：
1. CellDB.delete_layer 删除指定图层
2. CellDB.delete_layer 删除默认「工参图层」（含空/null layer_name 记录）
3. CellDB.clear_all_layers 清空所有图层
4. ParamLoader.load_from_sqlite 随数据库清空后的重置行为
5. main.py 中 cellsight_delete_layer 与 cellsight_clear_all_layers 的调用逻辑
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock
import pandas as pd
import pytest

from app.cell_db import CellDB
from app.param_loader import ParamLoader


def _sample_df():
    return pd.DataFrame([
        {
            "cell_name": "小区A1",
            "site_name": "基站A",
            "longitude": 113.31,
            "latitude": 23.11,
            "azimuth": 0,
            "rat": "4G",
            "layer_name": "电信4G",
        },
        {
            "cell_name": "小区A2",
            "site_name": "基站A",
            "longitude": 113.31,
            "latitude": 23.11,
            "azimuth": 120,
            "rat": "4G",
            "layer_name": "电信4G",
        },
        {
            "cell_name": "小区B1",
            "site_name": "基站B",
            "longitude": 113.32,
            "latitude": 23.12,
            "azimuth": 60,
            "rat": "5G",
            "layer_name": "移动5G",
        },
        {
            "cell_name": "小区C1",
            "site_name": "基站C",
            "longitude": 113.33,
            "latitude": 23.13,
            "azimuth": 180,
            "rat": "4G",
            "layer_name": "工参图层",
        },
    ])


class TestCellDBDelete:
    def test_delete_specific_layer(self, tmp_path):
        db_file = tmp_path / "test_cells.db"
        df = _sample_df()
        CellDB.save_dataframe(df, db_path=db_file, mode="replace")

        # 初始状态：4条记录，3个图层
        summary = CellDB.get_summary(db_path=db_file)
        assert summary["total_cells"] == 4
        layer_names = {l["name"] for l in summary["layers"]}
        assert layer_names == {"电信4G", "移动5G", "工参图层"}

        # 删除「电信4G」
        deleted = CellDB.delete_layer("电信4G", db_path=db_file)
        assert deleted == 2

        # 验证剩余记录
        summary2 = CellDB.get_summary(db_path=db_file)
        assert summary2["total_cells"] == 2
        layer_names2 = {l["name"] for l in summary2["layers"]}
        assert layer_names2 == {"移动5G", "工参图层"}

        remaining_df = CellDB.load_dataframe(db_file)
        assert len(remaining_df) == 2
        assert "电信4G" not in remaining_df["layer_name"].values

    def test_delete_default_layer_and_empty_names(self, tmp_path):
        db_file = tmp_path / "test_cells_default.db"
        df = pd.DataFrame([
            {"cell_name": "C1", "longitude": 113.1, "latitude": 23.1, "layer_name": "工参图层"},
            {"cell_name": "C2", "longitude": 113.2, "latitude": 23.2, "layer_name": ""},
            {"cell_name": "C3", "longitude": 113.3, "latitude": 23.3, "layer_name": None},
            {"cell_name": "C4", "longitude": 113.4, "latitude": 23.4, "layer_name": "其他图层"},
        ])
        CellDB.save_dataframe(df, db_path=db_file, mode="replace")

        deleted = CellDB.delete_layer("工参图层", db_path=db_file)
        # 应将 "工参图层", "" 和 None 均作为默认图层删除
        assert deleted == 3

        summary = CellDB.get_summary(db_path=db_file)
        assert summary["total_cells"] == 1
        assert summary["layers"][0]["name"] == "其他图层"

    def test_clear_all_layers(self, tmp_path):
        db_file = tmp_path / "test_clear.db"
        df = _sample_df()
        CellDB.save_dataframe(df, db_path=db_file, mode="replace")

        deleted = CellDB.clear_all_layers(db_path=db_file)
        assert deleted == 4

        summary = CellDB.get_summary(db_path=db_file)
        assert summary["total_cells"] == 0
        assert len(summary["layers"]) == 0

        df_empty = CellDB.load_dataframe(db_file)
        assert df_empty.empty

    def test_param_loader_resets_on_empty(self, tmp_path):
        db_file = tmp_path / "test_loader.db"
        df = _sample_df()
        CellDB.save_dataframe(df, db_path=db_file, mode="replace")

        loader = ParamLoader()
        loader.load_from_sqlite(str(db_file))
        assert loader.all_cells is not None
        assert len(loader.all_cells) == 4

        # 清空数据库后再次 load_from_sqlite
        CellDB.clear_all_layers(db_path=db_file)
        loader.load_from_sqlite(str(db_file))
        assert loader.all_cells is None
        summary = loader.get_summary()
        assert summary["total_cells"] == 0
        assert summary["total_sites"] == 0


@pytest.mark.anyio
async def test_main_delete_endpoints(tmp_path, monkeypatch):
    """测试 main.py 的 cellsight_delete_layer 与 cellsight_clear_all_layers 路由。"""
    import main

    test_db = tmp_path / "main_test.db"
    df = _sample_df()
    CellDB.save_dataframe(df, db_path=test_db, mode="replace")

    # 劫持 DEFAULT_DB_PATH
    monkeypatch.setattr("app.cell_db.DEFAULT_DB_PATH", test_db)

    # 初始载入
    main.param_loader.load_from_sqlite(str(test_db))
    main.session_state["params_loaded"] = True
    main.session_state["selected_cells"] = df.to_dict(orient="records")

    # 测试 POST 删除指定图层
    mock_request = MagicMock()
    mock_request.headers = {"content-type": "application/json"}
    mock_request.json = AsyncMock(return_value={"layer_name": "电信4G"})

    res = await main.cellsight_delete_layer(mock_request, layer_name=None)
    assert res["success"] is True
    assert res["deleted_count"] == 2
    assert main.param_loader.all_cells is not None
    assert len(main.param_loader.all_cells) == 2

    # 验证 selected_cells 中的电信4G小区已被移除
    assert len(main.session_state["selected_cells"]) == 2
    for c in main.session_state["selected_cells"]:
        assert c["layer_name"] != "电信4G"

    # 测试清空全部图层
    res_clear = await main.cellsight_clear_all_layers()
    assert res_clear["success"] is True
    assert res_clear["deleted_count"] == 2
    assert main.param_loader.all_cells is None
    assert main.session_state["params_loaded"] is False
    assert main.session_state["selected_cells"] is None
