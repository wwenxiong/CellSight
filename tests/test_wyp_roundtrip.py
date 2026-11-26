# -*- coding: utf-8 -*-
"""P1-7 .wyp 工程往返测试。

验证 app.project_manager.ProjectManager 的打包 / 解包往返一致性：
新建含视窗、图层、工参小区、标注、应急快照的工程 -> 打包成 .wyp 字节
-> 解包 -> 逐项比对内容一致。另覆盖磁盘往返与非法输入。

全部数据均为人工构造的假数据，不使用 data/ 下的真实工参。
"""

import io
import json
import zipfile
from datetime import datetime

import pytest

from app.project_manager import ProjectManager, PROJECT_VERSION


def _build_rich_project() -> dict:
    """构造一个内容丰富的假工程：视窗 + 样式 + 工参小区 + 标注 + 应急快照。"""
    project = ProjectManager.create_empty_project("往返测试工程")
    project["view_state"] = {
        "center": [106.550, 29.560],
        "zoom": 15,
        "tile_type": "amap_sat",
    }
    project["style_config"] = {
        "sector_beamwidth": 75,
        "sector_radius_mode": "band_adaptive",
        "color_mode": "pci",
        "show_labels": False,
        "show_cell_sectors": True,
        "layer_label_fields": {"4G工参": "cell_name", "5G工参": "pci"},
        "layer_label_lengths": {"4G工参": 8, "5G工参": 0},
    }
    project["layers"]["param_cells"] = [
        {
            "cell_name": "测试站A-1",
            "site_name": "测试站A",
            "cgi": "460001234567890",
            "cell_id": "1",
            "site_id": "900001",
            "rat": "4G",
            "freq_band": "1.8G",
            "pci": "100",
            "azimuth": 60,
            "tilt": 6,
            "longitude": 106.550,
            "latitude": 29.560,
            "cover_type": "室外",
        },
        {
            "cell_name": "测试站B-1",
            "site_name": "测试站B",
            "cgi": "460009876543210",
            "cell_id": "2",
            "site_id": "900002",
            "rat": "5G",
            "freq_band": "3.5G",
            "pci": "201",
            "azimuth": 180,
            "tilt": 4,
            "longitude": 106.560,
            "latitude": 29.570,
            "cover_type": "室外",
        },
    ]
    project["layers"]["annotations"] = [
        {"type": "point", "lng": 106.550, "lat": 29.560, "text": "测试标注点"},
        {
            "type": "polyline",
            "points": [[106.550, 29.560], [106.560, 29.570]],
            "text": "测距注记 1234.5m",
        },
        {
            "type": "polygon",
            "points": [[106.550, 29.560], [106.560, 29.560], [106.560, 29.570]],
            "text": "测试多边形",
        },
    ]
    project["layers"]["emergency_selection"] = {
        "geometry": {"type": "circle", "center": [106.550, 29.560], "radius_m": 3000},
        "selected_cells": ["460001234567890", "460009876543210"],
        "matched_alarms": [
            {"alarm_name": "测试告警", "cgi": "460001234567890", "level": "紧急"}
        ],
        "matched_kpi": [
            {"cgi": "460001234567890", "rrc_conn_max": 120, "prb_dl_util": 35.5}
        ],
        "diagnosed_cells": [
            {"cgi": "460001234567890", "diag_level": "正常", "diag_type": "运行平稳"}
        ],
    }
    return project


def test_create_empty_project_defaults():
    project = ProjectManager.create_empty_project()
    assert project["meta"]["name"] == "未命名网优工程"
    assert project["meta"]["version"] == PROJECT_VERSION
    assert project["view_state"]["zoom"] == 13
    assert project["style_config"]["sector_beamwidth"] == 65
    assert project["style_config"]["sector_radius_scale"] == 1.0
    assert project["style_config"]["layer_label_fields"] == {}
    assert project["style_config"]["layer_label_lengths"] == {}
    assert project["style_config"]["layer_label_visibility"] == {}
    assert project["style_config"]["layer_colors"] == {}
    assert project["layers"]["param_cells"] == []
    assert project["layers"]["annotations"] == []
    assert project["layers"]["emergency_selection"]["geometry"] is None


def test_pack_produces_valid_zip_with_manifest():
    project = _build_rich_project()
    blob = ProjectManager.pack_project_to_bytes(project)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    assert zipfile.is_zipfile(io.BytesIO(blob))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert set(zf.namelist()) == {"project.json", "manifest.json"}
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format"] == "wyp"
        assert manifest["version"] == PROJECT_VERSION
        assert manifest["entry"] == "project.json"
        assert manifest["cell_count"] == 2


def test_roundtrip_bytes_all_sections_equal():
    """核心往返：打包 -> 解包，视窗/样式/工参/标注/应急快照逐项一致。"""
    project = _build_rich_project()
    blob = ProjectManager.pack_project_to_bytes(project)
    restored = ProjectManager.unpack_project_from_bytes(blob)

    assert restored["view_state"] == project["view_state"]
    assert restored["style_config"] == project["style_config"]
    assert restored["layers"]["param_cells"] == project["layers"]["param_cells"]
    assert restored["layers"]["annotations"] == project["layers"]["annotations"]
    assert (
        restored["layers"]["emergency_selection"]
        == project["layers"]["emergency_selection"]
    )
    assert restored["meta"]["name"] == "往返测试工程"
    assert restored["meta"]["version"] == PROJECT_VERSION
    # pack 会刷新 updated_at：解包后应为合法时间戳
    datetime.strptime(restored["meta"]["updated_at"], "%Y-%m-%d %H:%M:%S")


def test_roundtrip_empty_project():
    blob = ProjectManager.pack_project_to_bytes(
        ProjectManager.create_empty_project("空工程")
    )
    restored = ProjectManager.unpack_project_from_bytes(blob)
    assert restored["meta"]["name"] == "空工程"
    assert restored["layers"]["param_cells"] == []
    assert restored["layers"]["emergency_selection"]["selected_cells"] == []


def test_roundtrip_via_disk(tmp_path):
    """磁盘往返：save -> load，内容一致。"""
    project = _build_rich_project()
    target = tmp_path / "sub" / "test.wyp"
    saved = ProjectManager.save_project_to_disk(project, str(target))
    assert saved.endswith("test.wyp")
    assert target.exists()
    restored = ProjectManager.load_project_from_disk(str(target))
    assert restored["view_state"] == project["view_state"]
    assert restored["layers"]["param_cells"] == project["layers"]["param_cells"]
    assert restored["layers"]["annotations"] == project["layers"]["annotations"]
    assert (
        restored["layers"]["emergency_selection"]
        == project["layers"]["emergency_selection"]
    )


def test_unpack_plain_json_compat():
    """兼容分支：纯 JSON 字节（非 ZIP）也能解包。"""
    project = _build_rich_project()
    raw = json.dumps(project, ensure_ascii=False).encode("utf-8")
    restored = ProjectManager.unpack_project_from_bytes(raw)
    assert restored["meta"]["name"] == "往返测试工程"
    assert len(restored["layers"]["param_cells"]) == 2


def test_unpack_invalid_bytes_raises():
    with pytest.raises(ValueError):
        ProjectManager.unpack_project_from_bytes(b"this is not a wyp file")


def test_unpack_zip_without_project_json_raises():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, mode="w") as zf:
        zf.writestr("other.txt", "hello")
    with pytest.raises(ValueError):
        ProjectManager.unpack_project_from_bytes(bio.getvalue())


def test_export_with_custom_save_path(tmp_path):
    """测试指定自定义磁盘路径另存工程文件。"""
    project = _build_rich_project()
    target = tmp_path / "custom_folder" / "my_custom_project.wyp"
    wyp_bytes = ProjectManager.pack_project_to_bytes(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        f.write(wyp_bytes)
    assert target.exists()
    assert target.stat().st_size > 0
    restored = ProjectManager.load_project_from_disk(str(target))
    assert restored["meta"]["name"] == "往返测试工程"
    assert len(restored["layers"]["param_cells"]) == 2


def test_cell_db_dynamic_columns_and_roundtrip(tmp_path):
    """测试 SQLite 数据库保存完全动态自定义表头及往返还原。"""
    import pandas as pd
    from app.cell_db import CellDB

    db_file = tmp_path / "test_cells.db"
    
    # 模拟包含任意自定义动态表头的数据集
    test_df = pd.DataFrame([
        {
            "cell_name": "测试小区1",
            "cgi": "460-00-1-1",
            "longitude": 106.512345,
            "latitude": 29.567890,
            "azimuth": 120.0,
            "tilt": 5.0,
            "厂商": "华为",
            "覆盖场景": "密集城区",
            "下行双工模式": "TDD",
            "特殊测试指标_score": 98.6,
        },
        {
            "cell_name": "测试小区2",
            "cgi": "460-00-1-2",
            "longitude": 106.520000,
            "latitude": 29.570000,
            "azimuth": 240.0,
            "tilt": 7.0,
            "厂商": "中兴",
            "覆盖场景": "商业区",
            "下行双工模式": "FDD",
            "特殊测试指标_score": 85.2,
        }
    ])

    # 1. 保存到 SQLite
    count = CellDB.save_dataframe(test_df, db_file)
    assert count == 2
    assert db_file.exists()

    # 2. 从 SQLite 读取
    loaded_df = CellDB.load_dataframe(db_file)
    assert len(loaded_df) == 2
    # 验证动态表头 100% 保留
    assert "厂商" in loaded_df.columns
    assert "覆盖场景" in loaded_df.columns
    assert "下行双工模式" in loaded_df.columns
    assert "特殊测试指标_score" in loaded_df.columns
    assert loaded_df.iloc[0]["厂商"] == "华为"
    assert loaded_df.iloc[1]["厂商"] == "中兴"

    # 3. 统计信息
    summary = CellDB.get_summary(db_file)
    assert summary["total_cells"] == 2

    # 4. 字节流提取与恢复
    db_bytes = CellDB.get_db_bytes(db_file)
    assert len(db_bytes) > 0

    restore_target = tmp_path / "restored.db"
    CellDB.restore_db_bytes(db_bytes, restore_target)
    assert restore_target.exists()
    restored_df = CellDB.load_dataframe(restore_target)
    assert len(restored_df) == 2
    assert restored_df.iloc[0]["cell_name"] == "测试小区1"


def test_wyp_pack_and_unpack_with_sqlite_db(tmp_path):
    """测试 .wyp 工程打包包含 cells.db，并在解包时完整还原 SQLite 数据库与动态列。"""
    import pandas as pd
    from app.cell_db import CellDB

    db_file = tmp_path / "source_cells.db"
    df = pd.DataFrame([
        {
            "cell_name": "工程自包含小区A",
            "cgi": "460-00-999-1",
            "longitude": 106.50,
            "latitude": 29.50,
            "azimuth": 30.0,
            "自定义VIP保障等级": "A级重大保障",
        }
    ])
    CellDB.save_dataframe(df, db_file)

    project = ProjectManager.create_empty_project("含数据库工程")
    # 打包工程同时内嵌 SQLite 数据库
    wyp_bytes = ProjectManager.pack_project_to_bytes(project, db_path=str(db_file))

    # 验证 zip 包内含有 cells.db
    with zipfile.ZipFile(io.BytesIO(wyp_bytes)) as zf:
        assert "cells.db" in zf.namelist()
        assert "project.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["has_sqlite_db"] is True

    # 解包并恢复到新的数据库路径
    extracted_db = tmp_path / "extracted_cells.db"
    restored_proj = ProjectManager.unpack_project_from_bytes(wyp_bytes, extract_db_path=str(extracted_db))
    assert restored_proj["meta"]["name"] == "含数据库工程"
    assert extracted_db.exists()

    # 验证解包还原的 SQLite 数据完整包含自定义动态列
    extracted_df = CellDB.load_dataframe(extracted_db)
    assert len(extracted_df) == 1
    assert extracted_df.iloc[0]["cell_name"] == "工程自包含小区A"
    assert extracted_df.iloc[0]["自定义VIP保障等级"] == "A级重大保障"
    # 同时验证 project_data 的 param_cells 被自动填充
    assert len(restored_proj["layers"]["param_cells"]) == 1
    assert restored_proj["layers"]["param_cells"][0]["cell_name"] == "工程自包含小区A"


def test_cell_db_append_mode_merges_4g_and_5g(tmp_path):
    """测试先导入 4G 工参，再以追加模式导入 5G 工参，两者成功合并且制式正确保留。"""
    import pandas as pd
    from app.cell_db import CellDB

    db_file = tmp_path / "multi_rat_cells.db"

    df_4g = pd.DataFrame([
        {"cell_name": "4G小区A", "cgi": "460-00-1-1", "rat": "4G", "longitude": 106.5, "latitude": 29.5, "azimuth": 0.0},
        {"cell_name": "4G小区B", "cgi": "460-00-1-2", "rat": "4G", "longitude": 106.6, "latitude": 29.6, "azimuth": 120.0},
    ])
    CellDB.save_dataframe(df_4g, db_file, mode="replace")

    summary1 = CellDB.get_summary(db_file)
    assert summary1["total_cells"] == 2
    assert summary1["lte_cells"] == 2
    assert summary1["nr_cells"] == 0

    # 追加 5G 工参
    df_5g = pd.DataFrame([
        {"cell_name": "5G小区C", "cgi": "460-00-2-1", "rat": "5G", "longitude": 106.7, "latitude": 29.7, "azimuth": 240.0},
    ])
    CellDB.save_dataframe(df_5g, db_file, mode="append")

    summary2 = CellDB.get_summary(db_file)
    assert summary2["total_cells"] == 3
    assert summary2["lte_cells"] == 2
    assert summary2["nr_cells"] == 1

    loaded = CellDB.load_dataframe(db_file)
    assert len(loaded) == 3
    assert set(loaded["rat"]) == {"4G", "5G"}


def test_cell_db_duplicate_column_names_safety(tmp_path):
    """测试同时包含 PCI 和 pci 等大小写重复或同名列时，SQLite 不报错且安全去重保存。"""
    import pandas as pd
    from app.cell_db import CellDB

    db_file = tmp_path / "dup_cols.db"

    # 模拟包含 PCI 与 pci，以及两个同名列的数据集
    dup_df = pd.DataFrame([
        {
            "PCI": 101,
            "pci": 101,
            "CGI": "460-00-1-1",
            "cgi": "460-00-1-1",
            "cell_name": "防重测小区",
            "longitude": 106.5,
            "latitude": 29.5,
            "azimuth": 0.0,
            "rat": "4G",
        }
    ])

    # 保存不应抛出 sqlite3.OperationalError: duplicate column name: pci
    count = CellDB.save_dataframe(dup_df, db_file)
    assert count == 1

    loaded = CellDB.load_dataframe(db_file)
    assert len(loaded) == 1
    assert "pci" in loaded.columns
    assert "cgi" in loaded.columns
    assert str(loaded.iloc[0]["pci"]) == "101"






def test_unpack_nan_cells_from_sqlite_are_json_safe(tmp_path):
    """回归：SQLite 里 NULL 读回为 NaN，解包后必须转 None，否则打开工程时
    Starlette JSONResponse（allow_nan=False）会报
    "Out of range float values are not JSON compliant: nan"。"""
    import pandas as pd
    from app.cell_db import CellDB

    db_file = tmp_path / "nan_cells.db"
    df = pd.DataFrame([
        {"cell_name": "全向站-1", "cgi": "460-00-1-1", "longitude": 106.5, "latitude": 29.5,
         "azimuth": None, "tilt": 6.0, "天线增益": 15.5},
        {"cell_name": "定向站-2", "cgi": "460-00-1-2", "longitude": 106.6, "latitude": 29.6,
         "azimuth": 120.0, "tilt": 6.0, "天线增益": None},
    ])
    CellDB.save_dataframe(df, db_file)

    project = ProjectManager.create_empty_project("含缺失值工程")
    wyp_bytes = ProjectManager.pack_project_to_bytes(project, db_path=str(db_file))

    extracted_db = tmp_path / "extracted.db"
    restored = ProjectManager.unpack_project_from_bytes(wyp_bytes, extract_db_path=str(extracted_db))
    cells = restored["layers"]["param_cells"]
    assert len(cells) == 2
    assert cells[0]["azimuth"] is None
    assert cells[1]["天线增益"] is None
    # 模拟 Starlette JSONResponse 的严格序列化
    json.dumps({"success": True, "project": restored}, ensure_ascii=False, allow_nan=False)


def test_unpack_cleans_nan_literals_in_project_json():
    """回归：旧工程文件 project.json 里已存有 NaN 字面量时，解包同样要清洗。"""
    project = ProjectManager.create_empty_project("旧文件工程")
    project["layers"]["param_cells"] = [
        {"cell_name": "旧小区", "cgi": "460-00-9-9", "longitude": 106.5, "latitude": 29.5,
         "azimuth": float("nan"), "tilt": 6.0},
    ]
    wyp_bytes = ProjectManager.pack_project_to_bytes(project)
    restored = ProjectManager.unpack_project_from_bytes(wyp_bytes)
    cells = restored["layers"]["param_cells"]
    assert cells[0]["azimuth"] is None
    json.dumps({"success": True, "project": restored}, ensure_ascii=False, allow_nan=False)


def test_wyp_roundtrip_preserves_field_render_state():
    """回归：按字段筛选 / 着色状态及用户自定义颜色（style_config.field_render）随 .wyp 往返保留。"""
    project = ProjectManager.create_empty_project("字段渲染工程")
    project["style_config"]["field_render"] = {
        "layerFilters": {"LTE图层": {"freq_band": ["1650", "2452"], "归属": ["渝北"]}},
        "layerColorFields": {"LTE图层": "归属", "NR图层": "freq_band"},
        "layerCustomColors": {"LTE图层": {"归属": {"渝北": "#ff0000", "江北": "#00ff00"}}}
    }
    blob = ProjectManager.pack_project_to_bytes(project)
    restored = ProjectManager.unpack_project_from_bytes(blob)
    assert restored["style_config"]["field_render"] == {
        "layerFilters": {"LTE图层": {"freq_band": ["1650", "2452"], "归属": ["渝北"]}},
        "layerColorFields": {"LTE图层": "归属", "NR图层": "freq_band"},
        "layerCustomColors": {"LTE图层": {"归属": {"渝北": "#ff0000", "江北": "#00ff00"}}}
    }
    # 严格 JSON 序列化（工程恢复响应的序列化条件）
    json.dumps({"success": True, "project": restored}, ensure_ascii=False, allow_nan=False)


def test_wyp_roundtrip_preserves_layer_styling_and_visibility():
    """回归：扇区大小缩放、张角、着色方案、图层显隐、标注开关完整往返保留。"""
    project = ProjectManager.create_empty_project("样式与图层状态工程")
    project["style_config"]["sector_radius_scale"] = 1.75
    project["style_config"]["sector_beamwidth"] = 45
    project["style_config"]["sector_color_mode"] = "pci"
    project["style_config"]["color_mode"] = "pci"
    project["style_config"]["show_labels"] = True
    project["style_config"]["layer_visibility"] = {
        "4G工参": False,
        "5G工参": True,
        "labels": True,
        "emergency": False
    }
    project["style_config"]["layer_label_visibility"] = {
        "4G工参": False,
        "5G工参": True
    }

    blob = ProjectManager.pack_project_to_bytes(project)
    restored = ProjectManager.unpack_project_from_bytes(blob)
    sc = restored["style_config"]
    assert sc["sector_radius_scale"] == 1.75
    assert sc["sector_beamwidth"] == 45
    assert sc["sector_color_mode"] == "pci"
    assert sc["show_labels"] is True
    assert sc["layer_visibility"] == {
        "4G工参": False,
        "5G工参": True,
        "labels": True,
        "emergency": False
    }
    assert sc["layer_label_visibility"] == {
        "4G工参": False,
        "5G工参": True
    }


def test_wyp_pack_dedup_when_sqlite_present_and_skip_redundant_save(tmp_path, monkeypatch):
    """验证含 SQLite 的 .wyp 打包瘦身去重，且解包恢复时不重复执行 save_dataframe 写库。"""
    import pandas as pd
    from unittest.mock import MagicMock
    from app.cell_db import CellDB
    import main

    db_path = tmp_path / "cells.db"
    df = pd.DataFrame([
        {
            "cell_name": "测试小区1",
            "site_name": "测试站1",
            "longitude": 107.51,
            "latitude": 29.71,
            "rat": "4G",
            "layer_name": "4G工参",
        }
    ])
    CellDB.save_dataframe(df, db_path=db_path)

    project = _build_rich_project()
    original_cell_count = len(project["layers"]["param_cells"])

    # 1. 携带 db_path 打包：project.json 内的 param_cells 应去重清空，但内存中原始 dict 不受影响
    blob = ProjectManager.pack_project_to_bytes(project, db_path=str(db_path))
    assert len(project["layers"]["param_cells"]) == original_cell_count

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert "cells.db" in zf.namelist()
        p_json = json.loads(zf.read("project.json").decode("utf-8"))
        assert p_json["layers"]["param_cells"] == []
        m_json = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert m_json["has_sqlite_db"] is True
        assert m_json["cell_count"] == original_cell_count

    # 2. 解包恢复：应直接从 cells.db 恢复并返回 preloaded_df，且不触发 save_dataframe
    extract_db = tmp_path / "restored.db"
    restored, restored_from_db, preloaded_df = ProjectManager.unpack_project_with_meta(
        blob, extract_db_path=str(extract_db)
    )
    assert restored_from_db is True
    assert preloaded_df is not None
    assert len(preloaded_df) == 1
    assert len(restored["layers"]["param_cells"]) == 1
    assert restored["layers"]["param_cells"][0]["cell_name"] == "测试小区1"

    mock_save = MagicMock()
    monkeypatch.setattr(CellDB, "save_dataframe", mock_save)
    monkeypatch.setattr("app.cell_db.DEFAULT_DB_PATH", extract_db)

    main._apply_project_cells_to_session(
        restored,
        restored_from_db=restored_from_db,
        preloaded_df=preloaded_df,
    )
    mock_save.assert_not_called()

