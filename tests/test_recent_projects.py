# -*- coding: utf-8 -*-
"""最近工程列表（P3-5）: 服务端存档 + 元数据维护的单元测试。"""
import json

import pytest

import main as cellsight_main


@pytest.fixture(autouse=True)
def _isolate_recent_store(tmp_path, monkeypatch):
    """把最近工程存档重定向到临时目录，不碰真实数据。"""
    store = tmp_path / "recent_projects"
    store.mkdir()
    monkeypatch.setattr(cellsight_main, "RECENT_PROJECTS_DIR", store)
    monkeypatch.setattr(cellsight_main, "RECENT_PROJECTS_META", tmp_path / "recent_projects.json")
    return store


def _fake_wyp_bytes():
    # 用最小合法工程包当作 .wyp 字节（ProjectManager 打包真实项目）
    from app.project_manager import ProjectManager
    return ProjectManager.pack_project_to_bytes(ProjectManager.create_empty_project(name="测试工程"))


def test_record_and_list_roundtrip(_isolate_recent_store):
    cellsight_main._record_recent_project("测试工程", _fake_wyp_bytes(), 3)
    items = cellsight_main._load_recent_projects_meta()
    assert len(items) == 1
    assert items[0]["name"] == "测试工程"
    assert items[0]["cell_count"] == 3
    assert items[0]["updated_at"]
    # 副本文件确实落盘
    assert (_isolate_recent_store / items[0]["filename"]).exists()


def test_recent_list_capped_at_five(_isolate_recent_store):
    for i in range(7):
        cellsight_main._record_recent_project(f"工程{i}", _fake_wyp_bytes(), i)
    items = cellsight_main._load_recent_projects_meta()
    assert len(items) == 5
    # 最新在最前
    assert items[0]["name"] == "工程6"
    assert items[-1]["name"] == "工程2"
    # 超出的旧副本已被清理
    assert len(list(_isolate_recent_store.iterdir())) == 5


def test_same_name_re_recorded_once(_isolate_recent_store):
    cellsight_main._record_recent_project("同名工程", _fake_wyp_bytes(), 1)
    cellsight_main._record_recent_project("同名工程", _fake_wyp_bytes(), 2)
    items = cellsight_main._load_recent_projects_meta()
    assert len(items) == 1
    assert items[0]["cell_count"] == 2
