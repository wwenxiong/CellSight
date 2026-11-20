# -*- coding: utf-8 -*-
"""app/pci_checker.py 单元测试：check_pci_conflicts 检出 / 不检出规则。

全部小区均为人工构造的假数据。
"""

import pytest

from app.pci_checker import check_pci_conflicts


def _cell(name, lng, lat, pci="100", rat="4G", band="1.8G", site=None):
    return {
        "cell_name": name,
        "site_name": site or f"测试站-{name}",
        "cgi": f"46000{name}",
        "pci": pci,
        "rat": rat,
        "freq_band": band,
        "longitude": lng,
        "latitude": lat,
        "azimuth": 0,
    }


class TestConflictDetected:
    def test_same_freq_same_pci_close(self):
        """同频同 PCI、相距约 1.1km -> 检出 1 对，严重度为严重（<3km）。"""
        cells = [
            _cell("A1", 106.500, 29.500),
            _cell("A2", 106.510, 29.500),  # 向东约 0.97km
        ]
        res = check_pci_conflicts(cells)
        assert res["total_conflicts"] == 1
        c = res["conflicts"][0]
        assert c["type"] == "同频同PCI冲突"
        assert c["severity"] == "严重"
        assert c["pci"] == "100"
        assert c["distance_m"] == pytest.approx(968.0, abs=10.0)
        assert c["cell_a"]["cell_name"] == "A1"
        assert c["cell_b"]["cell_name"] == "A2"

    def test_moderate_severity_between_3_and_6km(self):
        """同频同 PCI、相距约 4km -> 检出，严重度为中度。"""
        cells = [_cell("A1", 106.500, 29.500), _cell("A2", 106.541, 29.500)]
        res = check_pci_conflicts(cells)
        assert res["total_conflicts"] == 1
        assert res["conflicts"][0]["severity"] == "中度"
        assert res["conflicts"][0]["distance_m"] == pytest.approx(4000, abs=100)

    def test_band_case_insensitive(self):
        """频段大小写不敏感：1.8g 与 1.8G 应视为同频。"""
        cells = [
            _cell("A1", 106.500, 29.500, band="1.8g"),
            _cell("A2", 106.510, 29.500, band="1.8G"),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 1

    def test_custom_threshold(self):
        """自定义门限：相距 10km，默认 6km 不检出，门限 12km 检出。"""
        cells = [_cell("A1", 106.500, 29.500), _cell("A2", 106.603, 29.500)]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0
        assert check_pci_conflicts(cells, distance_threshold_m=12000)["total_conflicts"] == 1

    def test_conflicts_sorted_by_distance(self):
        """多对冲突按距离从近到远排序。"""
        cells = [
            _cell("A1", 106.500, 29.500),
            _cell("A2", 106.510, 29.500),  # ~1km
            _cell("A3", 106.530, 29.500),  # ~3km from A1, ~2km from A2
        ]
        res = check_pci_conflicts(cells)
        assert res["total_conflicts"] == 3
        dists = [c["distance_m"] for c in res["conflicts"]]
        assert dists == sorted(dists)


class TestNoConflict:
    def test_different_pci(self):
        cells = [
            _cell("A1", 106.500, 29.500, pci="100"),
            _cell("A2", 106.510, 29.500, pci="101"),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_different_band(self):
        cells = [
            _cell("A1", 106.500, 29.500, band="1.8G"),
            _cell("A2", 106.510, 29.500, band="2.1G"),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_different_rat(self):
        cells = [
            _cell("A1", 106.500, 29.500, rat="4G"),
            _cell("A2", 106.510, 29.500, rat="5G"),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_too_far_apart(self):
        """同频同 PCI 但相距约 10km（> 默认 6km 门限）-> 不检出。"""
        cells = [_cell("A1", 106.500, 29.500), _cell("A2", 106.603, 29.500)]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_empty_input(self):
        assert check_pci_conflicts([]) == {"total_conflicts": 0, "conflicts": []}

    def test_single_cell(self):
        assert check_pci_conflicts([_cell("A1", 106.500, 29.500)])["total_conflicts"] == 0


class TestInvalidCellsSkipped:
    @pytest.mark.parametrize("pci", ["0", "-", ""])
    def test_invalid_pci_skipped(self, pci):
        cells = [
            _cell("A1", 106.500, 29.500, pci=pci),
            _cell("A2", 106.510, 29.500, pci=pci),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    @pytest.mark.parametrize("pci", [None, float("nan")])
    def test_none_or_nan_pci_skipped(self, pci):
        cells = [
            _cell("A1", 106.500, 29.500, pci=pci),
            _cell("A2", 106.510, 29.500, pci=pci),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_zero_coordinates_skipped(self):
        cells = [
            _cell("A1", 0, 0),
            _cell("A2", 0, 0),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0

    def test_non_numeric_coordinates_skipped(self):
        cells = [
            _cell("A1", 106.500, 29.500),
            _cell("A2", "bad", "bad"),
        ]
        assert check_pci_conflicts(cells)["total_conflicts"] == 0
