/**
 * 按字段筛选 / 着色纯逻辑测试（Node 内置测试运行器）。
 *
 * 运行：node --test tests/test_field_render.mjs
 * 覆盖：取值归一化、图层字段列表、取值统计排序、筛选（单值/多值/多字段与/清空）、
 * 配色（≤10 / 超 10 归“其他”）、筛选 + 着色叠加。
 * 全部数据均为人工构造的假数据，不使用 data/ 下的真实工参。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const FR = require('../static/js/field_render.js');

const CELLS = [
    { cell_name: 'A-1', site_name: '站A', rat: '4G', freq_band: '1650', pci: '100', 归属: '渝北', layer_name: 'LTE图层' },
    { cell_name: 'A-2', site_name: '站A', rat: '4G', freq_band: '1650', pci: '101', 归属: '渝北', layer_name: 'LTE图层' },
    { cell_name: 'A-3', site_name: '站A', rat: '4G', freq_band: '2452', pci: '102', 归属: '江北', layer_name: 'LTE图层' },
    { cell_name: 'B-1', site_name: '站B', rat: '5G', freq_band: '3.5G', pci: '200', 归属: '渝北', layer_name: 'NR图层' },
    { cell_name: 'B-2', site_name: '站B', rat: '5G', freq_band: '3.5G', pci: '201', 归属: null,  layer_name: 'NR图层' },
];

test('displayValue：空值统一记为（空），数字转字符串', () => {
    assert.equal(FR.displayValue(null), '（空）');
    assert.equal(FR.displayValue(undefined), '（空）');
    assert.equal(FR.displayValue(''), '（空）');
    assert.equal(FR.displayValue(1650), '1650');
    assert.equal(FR.displayValue('3.5G'), '3.5G');
});

test('getLayerFields：只列该图层实际拥有的列；未知图层为空', () => {
    const fields = FR.getLayerFields(CELLS, 'LTE图层');
    assert.deepEqual(fields, ['cell_name', 'site_name', 'rat', 'freq_band', 'pci', '归属', 'layer_name']);
    assert.deepEqual(FR.getLayerFields(CELLS, '不存在的图层'), []);
});

test('getFieldValues：取值 + 数量，按数量降序、同数量按取值字典序', () => {
    const values = FR.getFieldValues(CELLS, 'LTE图层', 'freq_band');
    assert.deepEqual(values, [
        { value: '1650', count: 2 },
        { value: '2452', count: 1 },
    ]);
    // 空值也计入
    const owners = FR.getFieldValues(CELLS, 'NR图层', '归属');
    assert.deepEqual(owners, [
        { value: '渝北', count: 1 },
        { value: '（空）', count: 1 },
    ]);
});

test('matchCellFilter：无条件全过；单字段多值之间或', () => {
    assert.equal(FR.matchCellFilter(CELLS[0], null), true);
    assert.equal(FR.matchCellFilter(CELLS[0], {}), true);
    assert.equal(FR.matchCellFilter(CELLS[0], { freq_band: ['1650'] }), true);
    assert.equal(FR.matchCellFilter(CELLS[2], { freq_band: ['1650'] }), false);
    assert.equal(FR.matchCellFilter(CELLS[2], { freq_band: ['1650', '2452'] }), true);
    assert.equal(FR.matchCellFilter(CELLS[0], { freq_band: [] }), true); // 空值列表不限制
});

test('matchCellFilter：字段之间与；空值可筛', () => {
    assert.equal(FR.matchCellFilter(CELLS[0], { freq_band: ['1650'], 归属: ['渝北'] }), true);
    assert.equal(FR.matchCellFilter(CELLS[0], { freq_band: ['1650'], 归属: ['江北'] }), false);
    assert.equal(FR.matchCellFilter(CELLS[4], { 归属: ['（空）'] }), true);
    assert.equal(FR.matchCellFilter(CELLS[3], { 归属: ['（空）'] }), false);
});

test('filterCells：只筛有条件的图层，其他图层全过；空条件返回全量副本', () => {
    const filtered = FR.filterCells(CELLS, { 'LTE图层': { freq_band: ['1650'] } });
    assert.deepEqual(filtered.map(c => c.cell_name), ['A-1', 'A-2', 'B-1', 'B-2']);
    assert.deepEqual(FR.filterCells(CELLS, {}).map(c => c.cell_name), ['A-1', 'A-2', 'A-3', 'B-1', 'B-2']);
    assert.deepEqual(FR.filterCells(CELLS, null).map(c => c.cell_name), ['A-1', 'A-2', 'A-3', 'B-1', 'B-2']);
});

test('assignFieldColors：≤10 个取值各配一色，顺序与色板一致', () => {
    const assignment = FR.assignFieldColors([
        { value: '渝北', count: 3 },
        { value: '江北', count: 1 },
    ]);
    assert.equal(assignment.map.get('渝北'), FR.FIELD_PALETTE[0]);
    assert.equal(assignment.map.get('江北'), FR.FIELD_PALETTE[1]);
    assert.equal(assignment.otherCount, 0);
    assert.deepEqual(assignment.entries, [
        { value: '渝北', count: 3, color: FR.FIELD_PALETTE[0] },
        { value: '江北', count: 1, color: FR.FIELD_PALETTE[1] },
    ]);
    assert.equal(FR.getFieldColor('渝北', assignment), FR.FIELD_PALETTE[0]);
});

test('assignFieldColors：超 10 个取值时前 10 配色、其余归“其他”灰色', () => {
    const valueCounts = Array.from({ length: 12 }, (_, i) => ({ value: `V${i}`, count: 12 - i }));
    const assignment = FR.assignFieldColors(valueCounts);
    assert.equal(assignment.entries.length, 11); // 10 色 + 其他
    assert.equal(assignment.entries[10].value, '其他');
    assert.equal(assignment.entries[10].count, 3); // V10(2) + V11(1)
    assert.equal(assignment.entries[10].color, FR.OTHER_COLOR);
    assert.equal(FR.getFieldColor('V10', assignment), FR.OTHER_COLOR);
    assert.equal(FR.getFieldColor('V11', assignment), FR.OTHER_COLOR);
    assert.equal(FR.getFieldColor('没见过的值', assignment), FR.OTHER_COLOR);
    assert.equal(FR.getFieldColor('V0', null), FR.OTHER_COLOR);
});

test('assignFieldColors：支持用户自定义颜色覆盖默认色板', () => {
    const valueCounts = [
        { value: '渝北', count: 3 },
        { value: '江北', count: 1 },
    ];
    // 用户将“渝北”自定义为 #ff0000，未指定的“江北”沿用色板
    const assignment = FR.assignFieldColors(valueCounts, { '渝北': '#ff0000' });
    assert.equal(FR.getFieldColor('渝北', assignment), '#ff0000');
    assert.equal(FR.getFieldColor('江北', assignment), FR.FIELD_PALETTE[1]);
    assert.equal(assignment.entries[0].color, '#ff0000');
    assert.equal(assignment.entries[0].isCustom, true);
    assert.equal(assignment.entries[1].isCustom, false);
});

test('筛选 + 着色叠加：先筛 1650，再按归属配色，图例与地图一致', () => {
    const filtered = FR.filterCells(CELLS, { 'LTE图层': { freq_band: ['1650'] } });
    const values = FR.getFieldValues(filtered, 'LTE图层', '归属');
    assert.deepEqual(values, [{ value: '渝北', count: 2 }]);
    const assignment = FR.assignFieldColors(values);
    assert.equal(FR.getFieldColor('渝北', assignment), FR.FIELD_PALETTE[0]);
    // 清空筛选后恢复全量
    assert.equal(FR.filterCells(CELLS, {}).length, 5);
});
