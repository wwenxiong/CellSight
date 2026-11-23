/**
 * Wmap - 按工参字段筛选与着色（纯逻辑层，无 DOM 依赖，可用 Node 直接测试）
 *
 * 字段来源：导入工参文件的表头（SQLite 保留全部原始列），用户自由选择字段。
 * 规则：筛选按原始值；字段之间“与”，同一字段多个值之间“或”；
 * 着色固定 10 色色板，取值超过 10 个时按出现频次取前 10、其余归“其他”灰色。
 */

const WmapFieldRender = (function() {
    'use strict';

    // 固定 10 色色板（Tableau 10 分类色）
    const FIELD_PALETTE = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac'];
    const OTHER_COLOR = '#8e8e93'; // “其他”灰色
    const OTHER_LABEL = '其他';
    const MAX_COLOR_VALUES = 10;
    const EMPTY_LABEL = '（空）';

    function layerNameOf(cell) {
        return (cell.layer_name && String(cell.layer_name).trim()) ? String(cell.layer_name).trim() : '工参图层';
    }

    // 取值统一转显示字符串：null/undefined/'' 一律记为“（空）”，保证筛选与着色用同一把 key
    function displayValue(v) {
        if (v === null || v === undefined || v === '') return EMPTY_LABEL;
        return String(v);
    }

    // 该图层实际拥有的列（按首次出现顺序；同一图层各行列一致，取首行即可）
    function getLayerFields(cells, layerName) {
        for (let i = 0; i < (cells || []).length; i++) {
            if (layerNameOf(cells[i]) === layerName) return Object.keys(cells[i]);
        }
        return [];
    }

    // 该图层某字段的全部取值 + 数量，按数量降序（同数量按取值字典序，保证稳定）
    function getFieldValues(cells, layerName, field) {
        const counts = new Map();
        for (let i = 0; i < (cells || []).length; i++) {
            const cell = cells[i];
            if (layerNameOf(cell) !== layerName) continue;
            const key = displayValue(cell[field]);
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        const list = [];
        counts.forEach((count, value) => list.push({ value, count }));
        list.sort((a, b) => (b.count - a.count) || (a.value < b.value ? -1 : a.value > b.value ? 1 : 0));
        return list;
    }

    // 单个小区是否满足某图层的筛选条件：字段之间“与”，同一字段多个值之间“或”；无条件全过
    function matchCellFilter(cell, layerFilter) {
        if (!layerFilter) return true;
        const fields = Object.keys(layerFilter);
        for (let i = 0; i < fields.length; i++) {
            const values = layerFilter[fields[i]];
            if (!values || values.length === 0) continue;
            if (values.indexOf(displayValue(cell[fields[i]])) === -1) return false;
        }
        return true;
    }

    // 按图层筛选：layerFilters = { 图层名: { 字段: [取值...] } }
    function filterCells(cells, layerFilters) {
        if (!layerFilters || Object.keys(layerFilters).length === 0) return (cells || []).slice();
        return (cells || []).filter(cell => matchCellFilter(cell, layerFilters[layerNameOf(cell)]));
    }

    // 给取值配色：按数量取前 10 配色板，其余归“其他”灰色
    function assignFieldColors(valueCounts) {
        const entries = [];
        const map = new Map();
        let otherCount = 0;
        (valueCounts || []).forEach((item, idx) => {
            if (idx < MAX_COLOR_VALUES) {
                const color = FIELD_PALETTE[idx % FIELD_PALETTE.length];
                map.set(item.value, color);
                entries.push({ value: item.value, count: item.count, color });
            } else {
                otherCount += item.count;
            }
        });
        if (otherCount > 0) {
            entries.push({ value: OTHER_LABEL, count: otherCount, color: OTHER_COLOR });
        }
        return { map, entries, otherCount, otherColor: OTHER_COLOR };
    }

    // 查某取值的颜色：前 10 取色板色，其余灰色；未见过的值也灰色
    function getFieldColor(value, assignment) {
        if (!assignment) return OTHER_COLOR;
        return assignment.map.get(value) || OTHER_COLOR;
    }

    return {
        FIELD_PALETTE,
        OTHER_COLOR,
        OTHER_LABEL,
        MAX_COLOR_VALUES,
        EMPTY_LABEL,
        layerNameOf,
        displayValue,
        getLayerFields,
        getFieldValues,
        matchCellFilter,
        filterCells,
        assignFieldColors,
        getFieldColor
    };
})();

if (typeof window !== 'undefined') window.WmapFieldRender = WmapFieldRender;
if (typeof module !== 'undefined' && module.exports) module.exports = WmapFieldRender;
