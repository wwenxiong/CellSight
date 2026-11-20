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

