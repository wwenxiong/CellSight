# -*- coding: utf-8 -*-
"""app/smart_importer.py 单元测试：表头智能映射与标准化处理。

全部表格均为人工构造的假数据（写在 tmp_path 里），不使用 data/ 下的真实工参。
"""

import pytest

from app.smart_importer import SmartImporter


def _write_csv(tmp_path, name, header, rows):
    path = tmp_path / name
    lines = [",".join(header)]
    lines += [",".join(str(v) for v in r) for r in rows]
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return str(path)


class TestAnalyzeFile:
    def test_chinese_headers_mapped(self, tmp_path):
        """中文表头：小区名称/基站名称/经度/纬度/方位角/频段/PCI/小区ID 全部映射。"""
        path = _write_csv(
            tmp_path,
            "vendor.csv",
            ["小区名称", "基站名称", "经度", "纬度", "方位角", "频段", "PCI", "小区ID"],
            [["测试小区A1", "测试站A", "106.5", "29.5", "60", "1.8G", "100", "1"]],
        )
        res = SmartImporter.analyze_file(path)
        m = res["suggested_mapping"]
        assert m["cell_name"] == "小区名称"
        assert m["site_name"] == "基站名称"
        assert m["longitude"] == "经度"
        assert m["latitude"] == "纬度"
        assert m["azimuth"] == "方位角"
        assert m["freq_band"] == "频段"
        assert m["pci"] == "PCI"
        assert m["cell_id"] == "小区ID"
        assert res["total_sample_rows"] == 1
        assert res["preview_data"][0]["小区名称"] == "测试小区A1"

    def test_english_alias_headers_mapped(self, tmp_path):
        """英文别名表头：CELL_NAME / LNG / LAT 映射到标准字段。"""
        path = _write_csv(
            tmp_path,
            "en.csv",
            ["CELL_NAME", "LNG", "LAT"],
            [["TestCell", "106.5", "29.5"]],
        )
        m = SmartImporter.analyze_file(path)["suggested_mapping"]
        assert m["cell_name"] == "CELL_NAME"
        assert m["longitude"] == "LNG"
        assert m["latitude"] == "LAT"

    def test_missing_required_columns_not_mapped(self, tmp_path):
        """缺经纬度列：映射里不应出现 longitude / latitude。"""
        path = _write_csv(
            tmp_path, "partial.csv", ["小区名称", "方位角"], [["测试小区A1", "60"]]
        )
        m = SmartImporter.analyze_file(path)["suggested_mapping"]
        assert m["cell_name"] == "小区名称"
        assert "longitude" not in m
        assert "latitude" not in m


class TestProcessAndStandardize:
    def _standard_file(self, tmp_path):
        header = ["小区名称", "基站名称", "经度", "纬度", "方位角", "频段", "PCI", "小区ID"]
        rows = [
            ["测试小区A1", "测试站A", "106.5", "29.5", "60", "1.8G", "100", "1"],
            ["测试小区B1", "", "106.6", "29.6", "400", "3.5G", "201", "2"],
            ["测试小区C-NR", "测试站C", "106.7", "29.7", "-30", "3.5G", "301", "3"],
            ["坏坐标小区", "测试站D", "abc", "29.5", "0", "1.8G", "102", "4"],
        ]
        return _write_csv(tmp_path, "std.csv", header, rows)

    def test_full_pipeline_wgs84(self, tmp_path):
        """WGS-84 全流程：坏坐标行剔除、方位角归一化、站名补全、制式推断。"""
        path = self._standard_file(tmp_path)
        mapping = SmartImporter.analyze_file(path)["suggested_mapping"]
        df = SmartImporter.process_and_standardize(path, mapping, coord_sys="WGS-84")

        assert len(df) == 3  # 坏坐标行被剔除
        assert df["azimuth"].tolist() == [60.0, 40.0, 330.0]  # 400->40, -30->330
        assert df["rat"].tolist() == ["4G", "4G", "5G"]  # 名字含 NR -> 5G
        assert df.iloc[1]["tilt"] == 0.0  # 缺失下倾角默认 0
        assert df.iloc[1]["height"] == 25.0  # 缺失挂高默认 25
        # 双坐标列已生成，且 GCJ-02 与 WGS-84 不同
        assert "longitude_gcj" in df.columns and "latitude_gcj" in df.columns
        assert (df["longitude_gcj"] != df["longitude"]).all()
        # 未映射的 cgi 列应存在且为空
        assert "cgi" in df.columns
        assert (df["cgi"] == "").all()

    def test_gcj02_input_converted_to_wgs84(self, tmp_path):
        """GCJ-02 输入：longitude_gcj 保留原值，longitude/latitude 转回 WGS-84。"""
        # GCJ-02 坐标，对应 WGS-84 (106.5, 29.5)
        path = _write_csv(
            tmp_path,
            "gcj.csv",
            ["小区名称", "经度", "纬度"],
            [["测试小区G1", "106.50384571576511", "29.49726370684094"]],
        )
        mapping = SmartImporter.analyze_file(path)["suggested_mapping"]
        df = SmartImporter.process_and_standardize(path, mapping, coord_sys="GCJ-02")
        assert len(df) == 1
        assert df.iloc[0]["longitude_gcj"] == pytest.approx(106.50384571576511)
        assert df.iloc[0]["latitude_gcj"] == pytest.approx(29.49726370684094)
        assert df.iloc[0]["longitude"] == pytest.approx(106.5, abs=1e-4)
        assert df.iloc[0]["latitude"] == pytest.approx(29.5, abs=1e-4)

    def test_missing_required_column_yields_empty(self, tmp_path):
        """缺经纬度映射：所有行因经纬度为空被剔除，结果为空表。"""
        path = _write_csv(
            tmp_path, "partial.csv", ["小区名称", "方位角"], [["测试小区A1", "60"]]
        )
        mapping = SmartImporter.analyze_file(path)["suggested_mapping"]
        df = SmartImporter.process_and_standardize(path, mapping)
        assert len(df) == 0
        assert "longitude" in df.columns


class TestTemplates:
    def test_save_and_load_template(self, tmp_path, monkeypatch):
        """映射模板保存/加载往返（模板文件重定向到 tmp_path，不碰 data/ 目录）。"""
        monkeypatch.setattr(
            "app.smart_importer.TEMPLATE_STORAGE_FILE", tmp_path / "tpl.json"
        )
        SmartImporter.save_template(
            "测试模板", {"cell_name": "小区名称", "longitude": "经度"}
        )
        templates = SmartImporter.load_templates()
        assert templates["测试模板"] == {"cell_name": "小区名称", "longitude": "经度"}

    def test_load_templates_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.smart_importer.TEMPLATE_STORAGE_FILE", tmp_path / "nope.json"
        )
        assert SmartImporter.load_templates() == {}


def test_empty_site_name_filled_from_cell_name(tmp_path):
    """空基站名应默认用小区名称补全。"""
    path = _write_csv(
        tmp_path,
        "empty_site.csv",
        ["小区名称", "基站名称", "经度", "纬度"],
        [["测试小区B1", "", "106.6", "29.6"]],
    )
    mapping = SmartImporter.analyze_file(path)["suggested_mapping"]
    df = SmartImporter.process_and_standardize(path, mapping, coord_sys="WGS-84")
    assert len(df) == 1
    assert df.iloc[0]["site_name"] == "测试小区B1"


def test_cell_id_only_header_not_stolen_by_cell_name(tmp_path):
    """只有“小区ID”列时，应映射到 cell_id，而不是被 cell_name 抢走。"""
    path = _write_csv(
        tmp_path,
        "id_only.csv",
        ["小区ID", "经度", "纬度"],
        [["1001", "106.5", "29.5"]],
    )
    m = SmartImporter.analyze_file(path)["suggested_mapping"]
    assert m["cell_id"] == "小区ID"
    assert "cell_name" not in m
