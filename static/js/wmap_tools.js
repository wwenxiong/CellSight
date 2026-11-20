/**
 * Wmap - 专业无线网优工具箱 (测距测角、PCI冲突分析与工程管理交互)
 */

const WmapTools = (function() {
    'use strict';

    let isMeasuring = false;
    let measurePoints = [];
    let measureLayerGroup = null;
    let tempLine = null;
    let tempTooltip = null;

    /**
     * 计算两点间球面距离(米)与真北方位角(度)
     */
    function computeDistanceAndBearing(lat1, lon1, lat2, lon2) {
        const R = 6378137.0;
        const dLat = (lat2 - lat1) * Math.PI / 180.0;
        const dLon = (lon2 - lon1) * Math.PI / 180.0;
        const rLat1 = lat1 * Math.PI / 180.0;
        const rLat2 = lat2 * Math.PI / 180.0;

        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(rLat1) * Math.cos(rLat2) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        const dist = R * c;

        // 方位角
        const y = Math.sin(dLon) * Math.cos(rLat2);
        const x = Math.cos(rLat1) * Math.sin(rLat2) -
                  Math.sin(rLat1) * Math.cos(rLat2) * Math.cos(dLon);
        let brng = Math.atan2(y, x) * 180.0 / Math.PI;
        brng = (brng + 360.0) % 360.0;

        return { distance: dist, bearing: brng };
    }

    /**
     * 初始化测距测角工具
     */
    function initMeasureTool(map) {
        if (!measureLayerGroup) {
            measureLayerGroup = L.featureGroup().addTo(map);
        }

        map.on('click', function(e) {
            if (!isMeasuring) return;
            const pt = [e.latlng.lat, e.latlng.lng];
            measurePoints.push(pt);

            // 绘制顶点标记
            const marker = L.circleMarker(pt, {
                radius: 4,
                color: '#38bdf8',
                fillColor: '#ffffff',
                fillOpacity: 1,
                weight: 2
            }).addTo(measureLayerGroup);

            if (measurePoints.length > 1) {
                const prev = measurePoints[measurePoints.length - 2];
                const res = computeDistanceAndBearing(prev[0], prev[1], pt[0], pt[1]);
                
                // 固定连线
                L.polyline([prev, pt], {
                    color: '#38bdf8',
                    weight: 2.5,
                    dashArray: '5, 5'
                }).addTo(measureLayerGroup);

                // 悬浮标注
                const distStr = res.distance >= 1000 ? `${(res.distance / 1000).toFixed(2)} km` : `${Math.round(res.distance)} m`;
                const label = L.marker(pt, {
                    icon: L.divIcon({
                        className: 'wmap-measure-label',
                        html: `<div style="background:rgba(15,23,42,0.88); border:1px solid #38bdf8; color:#38bdf8; font-size:11px; padding:2px 6px; border-radius:4px; white-space:nowrap; transform:translate(10px, -15px); font-family:monospace; box-shadow:0 2px 6px rgba(0,0,0,0.5);">
                                <b>${distStr}</b> · <b>${res.bearing.toFixed(1)}°</b>
                               </div>`
                    })
                }).addTo(measureLayerGroup);
            }
        });

        map.on('mousemove', function(e) {
            if (!isMeasuring || measurePoints.length === 0) return;
            const lastPt = measurePoints[measurePoints.length - 1];
            const currPt = [e.latlng.lat, e.latlng.lng];

            if (!tempLine) {
                tempLine = L.polyline([lastPt, currPt], {
                    color: '#fbbf24',
                    weight: 1.5,
                    dashArray: '4, 4'
                }).addTo(measureLayerGroup);
            } else {
                tempLine.setLatLngs([lastPt, currPt]);
            }

            const res = computeDistanceAndBearing(lastPt[0], lastPt[1], currPt[0], currPt[1]);
            const distStr = res.distance >= 1000 ? `${(res.distance / 1000).toFixed(2)} km` : `${Math.round(res.distance)} m`;

            if (!tempTooltip) {
                tempTooltip = L.tooltip({
                    permanent: true,
                    direction: 'right',
                    offset: [15, 0],
                    className: 'wmap-measure-temp-tip'
                }).setLatLng(currPt).setContent(`距离: ${distStr} | 方位: ${res.bearing.toFixed(1)}°`).addTo(map);
            } else {
                tempTooltip.setLatLng(currPt).setContent(`距离: ${distStr} | 方位: ${res.bearing.toFixed(1)}°`);
            }
        });

        map.on('dblclick', function(e) {
            if (isMeasuring) {
                stopMeasuring();
            }
        });
    }

    function toggleMeasuring(map) {
        if (isMeasuring) {
            stopMeasuring();
        } else {
            startMeasuring(map);
        }
    }

    function startMeasuring(map) {
        isMeasuring = true;
        measurePoints = [];
        if (map) {
            map.getContainer().style.cursor = 'crosshair';
            initMeasureTool(map);
        }
        if (typeof showToast === 'function') {
            showToast('已激活测距测角工具：单击标定起点与折点，双击或Esc结束', 'info');
        }
        const btn = document.getElementById('toolBtnMeasure');
        if (btn) btn.classList.add('active');
    }

    function stopMeasuring() {
        isMeasuring = false;
        measurePoints = [];
        if (tempLine) {
            if (measureLayerGroup) measureLayerGroup.removeLayer(tempLine);
            tempLine = null;
        }
        if (tempTooltip) {
            tempTooltip.remove();
            tempTooltip = null;
        }
        if (window.appState && window.appState.map) {
            window.appState.map.getContainer().style.cursor = '';
        }
        const btn = document.getElementById('toolBtnMeasure');
        if (btn) btn.classList.remove('active');
    }

    function clearMeasurements() {
        stopMeasuring();
        if (measureLayerGroup) {
            measureLayerGroup.clearLayers();
        }
    }

    return {
        computeDistanceAndBearing,
        toggleMeasuring,
        startMeasuring,
        stopMeasuring,
        clearMeasurements
    };
})();

if (typeof window !== 'undefined') {
    window.WmapTools = WmapTools;
}
