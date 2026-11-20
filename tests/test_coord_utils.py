# -*- coding: utf-8 -*-
"""app/coord_utils.py 单元测试：WGS-84 <-> GCJ-02、境外判定、距离/方位角、坐标解析。"""

import math

import pytest

from app.coord_utils import (
    calculate_distance_and_bearing,
    destination_point,
    gcj02_to_wgs84,
    is_out_of_china,
    parse_coordinates,
    wgs84_to_gcj02,
)


# 重庆、北京、上海三个境内点（假测试坐标，仅用于算法验证）
CITIES = [(106.5, 29.5), (116.4, 39.9), (121.47, 31.23)]


class TestWgsGcjConversion:
    def test_forward_produces_offset_in_china(self):
        """境内 WGS-84 转 GCJ-02 应产生几百米量级的偏移（约 0.001~0.01 度）。"""
        for lng, lat in CITIES:
            gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
            assert (gcj_lng, gcj_lat) != (lng, lat)
            assert 0.0005 < abs(gcj_lng - lng) < 0.02
            assert 0.0005 < abs(gcj_lat - lat) < 0.02

    @pytest.mark.parametrize("lng,lat", CITIES)
    def test_roundtrip_error_below_1e6(self, lng, lat):
        """往返误差 < 1e-6 度（约 0.1 米量级）。"""
        gcj = wgs84_to_gcj02(lng, lat)
        back = gcj02_to_wgs84(*gcj)
        assert abs(back[0] - lng) < 1e-6
        assert abs(back[1] - lat) < 1e-6

    @pytest.mark.parametrize(
        "lng,lat",
        [
            (0.0, 0.0),  # 大西洋
            (-122.4194, 37.7749),  # 旧金山
            (139.7670, 35.6812),  # 东京
            (2.3522, 48.8566),  # 巴黎
        ],
    )
    def test_outside_china_returns_identity(self, lng, lat):
        """境外坐标原样返回，不加偏。"""
        assert wgs84_to_gcj02(lng, lat) == (lng, lat)
        assert gcj02_to_wgs84(lng, lat) == (lng, lat)


class TestIsOutOfChina:
    def test_inside(self):
        assert is_out_of_china(106.5, 29.5) is False
        assert is_out_of_china(116.4, 39.9) is False
        assert is_out_of_china(87.6, 43.8) is False  # 乌鲁木齐

    def test_outside(self):
        assert is_out_of_china(0.0, 0.0) is True
        assert is_out_of_china(140.0, 35.0) is True
        assert is_out_of_china(106.5, 60.0) is True

    def test_boundary_is_inside(self):
        # 边界值本身判定为境内（实现用严格 < / > 判断）
        assert is_out_of_china(72.004, 35.0) is False
        assert is_out_of_china(137.8347, 35.0) is False
        assert is_out_of_china(72.003, 35.0) is True


class TestDistanceAndBearing:
    def test_due_north_one_degree(self):
        dist, bearing = calculate_distance_and_bearing(106.5, 29.5, 106.5, 30.5)
        assert dist == pytest.approx(111319.49, abs=1.0)
        assert bearing == pytest.approx(0.0, abs=0.1)

    def test_due_east_one_degree(self):
        # 沿纬线向东 1 度：大圆初始方位略小于 90 度
        dist, bearing = calculate_distance_and_bearing(106.5, 29.5, 107.5, 29.5)
        assert dist == pytest.approx(96887.25, abs=1.0)
        assert bearing == pytest.approx(89.8, abs=0.3)

    def test_same_point(self):
        dist, bearing = calculate_distance_and_bearing(106.5, 29.5, 106.5, 29.5)
        assert dist == 0.0
        assert bearing == 0.0

    def test_south_is_180(self):
        _, bearing = calculate_distance_and_bearing(106.5, 30.5, 106.5, 29.5)
        assert bearing == pytest.approx(180.0, abs=0.1)

    def test_destination_then_measure_roundtrip(self):
        lng, lat = 106.5, 29.5
        dest = destination_point(lng, lat, 1000.0, 90.0)
        dist, bearing = calculate_distance_and_bearing(lng, lat, *dest)
        assert dist == pytest.approx(1000.0, abs=2.0)
        assert bearing == pytest.approx(90.0, abs=0.5)


class TestDestinationPoint:
    def test_1000m_north(self):
        lng, lat = destination_point(106.5, 29.5, 1000.0, 0.0)
        # 1 度纬度约 111319.49 米
        assert lat == pytest.approx(29.5 + 1000.0 / 111319.49, abs=1e-5)
        assert lng == pytest.approx(106.5, abs=1e-6)

    def test_zero_distance(self):
        assert destination_point(106.5, 29.5, 0.0, 45.0) == (106.5, 29.5)


class TestParseCoordinates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("106.5, 29.5", (106.5, 29.5)),
            ("106.5 29.5", (106.5, 29.5)),
            ("106.5，29.5", (106.5, 29.5)),
            ("经度: 106.5, 纬度: 29.5", (106.5, 29.5)),
            ("lat: 29.5, lng: 106.5", (106.5, 29.5)),
        ],
    )
    def test_valid_formats(self, text, expected):
        assert parse_coordinates(text) == expected

    def test_swapped_lat_lng_auto_corrected(self):
        # 经纬度倒置（纬度值 > 90）应自动纠偏
        assert parse_coordinates("29.5, 106.5") == (106.5, 29.5)

    @pytest.mark.parametrize("text", ["", "abc", "106.5", "106.5, 29.5, 10", "999, 999"])
    def test_invalid_returns_none(self, text):
        assert parse_coordinates(text) is None
