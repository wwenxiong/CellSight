/**
 * Wmap - 专业无线网优扇区几何与样式渲染引擎
 * 负责计算基站扇区波瓣多边形、全向站圆、频段阶梯半径与着色方案
 */

const WmapSector = (function() {
    'use strict';

    // 地球长半轴 (米)
    const EARTH_RADIUS = 6378137.0;

    /**
     * 球面上由起点经纬度、距离(米)与方位角(度)推算目标点经纬度
     */
    function destinationPoint(lat, lng, distanceMeters, bearingDegrees) {
        const delta = distanceMeters / EARTH_RADIUS;
        const theta = (bearingDegrees * Math.PI) / 180.0;
        const phi1 = (lat * Math.PI) / 180.0;
        const lambda1 = (lng * Math.PI) / 180.0;

        const sinPhi1 = Math.sin(phi1);
        const cosPhi1 = Math.cos(phi1);
        const sinDelta = Math.sin(delta);
        const cosDelta = Math.cos(delta);

        const phi2 = Math.asin(sinPhi1 * cosDelta + cosPhi1 * sinDelta * Math.cos(theta));
        const lambda2 = lambda1 + Math.atan2(
            Math.sin(theta) * sinDelta * cosPhi1,
            cosDelta - sinPhi1 * Math.sin(phi2)
        );

        return [ (phi2 * 180.0) / Math.PI, (lambda2 * 180.0) / Math.PI ];
    }

    /**
     * 生成扇区波瓣的多边形顶点数组 [[lat, lng], [lat, lng], ...]
     * @param {number} lat 站址纬度
     * @param {number} lng 站址经度
     * @param {number} azimuth 天线方位角 (0-360, 正北为0)
     * @param {number} beamwidth 水平波瓣张角 (默认 65°)
     * @param {number} radius 半径 (米)
     * @param {number} stepAngle 弧线离散步长 (度)
     */
    function getSectorPolygonCoordinates(lat, lng, azimuth, beamwidth = 65, radius = 120, stepAngle = 5) {
        const coords = [[lat, lng]]; // 起点：基站物理中心
        const halfAngle = beamwidth / 2.0;
        const startAngle = azimuth - halfAngle;
        const endAngle = azimuth + halfAngle;

        for (let a = startAngle; a <= endAngle; a += stepAngle) {
            coords.push(destinationPoint(lat, lng, radius, (a + 360) % 360));
        }
        // 确保圆弧终点闭合
        coords.push(destinationPoint(lat, lng, radius, (endAngle + 360) % 360));
        coords.push([lat, lng]); // 回到中心闭合
        return coords;
    }

    /**
     * 依据频段/制式智能推算建议的扇区半径 (米)
     */
    function getAdaptiveRadius(cell) {
        const band = String(cell.freq_band || '').toUpperCase();
        const rat = String(cell.rat || '4G').toUpperCase();

        // 700M / 800M / 900M 低频
        if (band.includes('700') || band.includes('800') || band.includes('900') || band === 'B8' || band === 'B20' || band === 'N28') {
            return 190;
        }
        // 1.8G / 2.1G 中频
        if (band.includes('1.8') || band.includes('1800') || band.includes('2.1') || band.includes('2100') || band === 'B1' || band === 'B3' || band === 'N1') {
            return 140;
        }
        // 2.6G / 3.5G / 4.9G 高频
        if (band.includes('2.6') || band.includes('2600') || band.includes('3.5') || band.includes('3500') || band.includes('4.9') || band === 'B41' || band === 'N78' || band === 'N79') {
            return 95;
        }

        // 制式默认
        if (rat === '5G') return 110;
        return 150;
    }

    /**
     * 根据着色模式获取扇区颜色配置
     * mode: 'rat' | 'freq_band' | 'pci' | 'alarm'
     * fieldStyle: 图层级字段着色 { color, label }，优先于全局模式，告警除外
     */
    function getSectorColors(cell, mode = 'rat', alarmMap = null, fieldStyle = null) {
        // 1. 告警诊断优先（如有）
        if (mode === 'alarm' || alarmMap) {
            const key = (cell.cell_name || '').toLowerCase();
            const idKey = (cell.cell_id !== undefined && cell.cell_id !== null) ? String(cell.cell_id).toLowerCase() : '';
            const cgiKey = (cell.cgi || '').toLowerCase();
            const alarm = (alarmMap && (alarmMap.get(key) || alarmMap.get(idKey) || alarmMap.get(cgiKey)));
            if (alarm) {
                if (alarm.diag_level === 'P0') return { stroke: '#ef4444', fill: '#ef4444', label: 'P0 退服断站' };
                if (alarm.diag_level === 'P1') return { stroke: '#f97316', fill: '#f97316', label: 'P1 高负荷' };
                if (alarm.diag_level === 'P2') return { stroke: '#eab308', fill: '#eab308', label: 'P2 质差' };
            }
        }

        // 1.5 按字段着色（图层级字段着色，优先于全局模式）
        if (fieldStyle && fieldStyle.color) {
            return { stroke: fieldStyle.color, fill: fieldStyle.color, label: fieldStyle.label || '' };
        }

        const rat = String(cell.rat || '').toUpperCase();
        const is5G = (rat === '5G' || rat === 'NR' || (cell.layer_name && /5G|NR/i.test(cell.layer_name)));

        // 2. 按 PCI 模 3 着色
        if (mode === 'pci') {
            const pci = parseInt(cell.pci, 10);
            if (!isNaN(pci)) {
                const mod3 = pci % 3;
                if (mod3 === 0) return { stroke: '#ef4444', fill: '#ef4444', label: 'PCI模3=0' };
                if (mod3 === 1) return { stroke: '#22c55e', fill: '#22c55e', label: 'PCI模3=1' };
                if (mod3 === 2) return { stroke: '#3b82f6', fill: '#3b82f6', label: 'PCI模3=2' };
            }
        }

        // 3. 按频段着色
        if (mode === 'freq_band') {
            const band = String(cell.freq_band || '').toUpperCase();
            if (band.includes('700') || band.includes('N28')) return { stroke: '#10b981', fill: '#10b981', label: '700M' };
            if (band.includes('900') || band.includes('B8')) return { stroke: '#06b6d4', fill: '#06b6d4', label: '900M' };
            if (band.includes('1.8') || band.includes('B3')) return { stroke: '#3b82f6', fill: '#3b82f6', label: '1.8G' };
            if (band.includes('2.1') || band.includes('B1') || band.includes('N1')) return { stroke: '#8b5cf6', fill: '#8b5cf6', label: '2.1G' };
            if (band.includes('2.6') || band.includes('B41') || band.includes('N41')) return { stroke: '#ec4899', fill: '#ec4899', label: '2.6G' };
            if (band.includes('3.5') || band.includes('N78')) return { stroke: '#f59e0b', fill: '#f59e0b', label: '3.5G' };
        }

        // 4. 默认按网络制式 (4G 浅蓝 / 5G 紫粉)
        if (is5G) {
            return { stroke: '#c084fc', fill: '#c084fc', label: '5G NR' };
        }
        return { stroke: '#38bdf8', fill: '#38bdf8', label: '4G LTE' };
    }

    /**
     * 计算扇区字段文字的最佳定位坐标 [lat, lng]
     * 准确沿扇区主瓣中轴线向外延伸，落入扇区内部中心腹地，杜绝超出扇区或站址重叠
     */
    function getSectorLabelCoordinates(lat, lng, azimuth, radius = 120, isOmni = false) {
        if (isOmni) {
            // 全向站：置于圆心正下方稍偏外侧
            return destinationPoint(lat, lng, Math.max(12, radius * 0.55), 180);
        }
        // 定向扇区：沿波瓣主轴中心方位角向外延伸 0.52 倍半径，稳稳居于扇区多边形内部核心腹地
        const dist = Math.max(14, radius * 0.52);
        const az = ((parseFloat(azimuth) || 0) % 360 + 360) % 360;
        return destinationPoint(lat, lng, dist, az);
    }

    /**
     * 判断是否为全向站 / 室分
     */
    function isOmniCell(cell) {
        const cover = String(cell.cover_type || '').toLowerCase();
        if (cover.includes('室') || cover.includes('分') || cover.includes('indoor')) {
            return true;
        }
        if (cell.azimuth === null || cell.azimuth === undefined || cell.azimuth === '') {
            return true;
        }
        const az = parseFloat(cell.azimuth);
        if (isNaN(az) || az >= 361) {
            return true;
        }
        return false;
    }

    return {
        destinationPoint,
        getSectorPolygonCoordinates,
        getAdaptiveRadius,
        getSectorColors,
        getSectorLabelCoordinates,
        isOmniCell
    };
})();

// 暴露给全局 window
if (typeof window !== 'undefined') {
    window.WmapSector = WmapSector;
}
