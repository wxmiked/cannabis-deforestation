/**
 * Cannabis Deforestation Story Map
 * Leaflet + Scrollama scrollytelling application
 */

(function () {
    'use strict';

    // ── Configuration ──
    var MAP_CENTER = [38.19, -120.65];
    var MAP_ZOOM = 11;

    // Planetary Computer mosaic tile endpoint (COG-backed, no local tiles needed)
    var PC_BASE = 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic';
    var PC_TILE_PARAMS = 'collection=naip&assets=image&asset_bidx=image%7C1%2C2%2C3';

    // Bounding box covering all cannabis parcels (with buffer)
    var PARCEL_BBOX = [[-120.98,37.92],[-120.31,37.92],[-120.31,38.46],[-120.98,38.46],[-120.98,37.92]];

    var TILE_OPTIONS = {
        minZoom: 11,
        maxNativeZoom: 18,
        maxZoom: 20,
        tms: false,
        attribution: 'NAIP Imagery &copy; USDA via <a href="https://planetarycomputer.microsoft.com">Planetary Computer</a>'
    };

    // ── State ──
    var map;
    var layers = {};
    var parcelsLayer;
    var detectionsLayer;
    var countyBoundaryLayer;
    var butteFireLayer;
    var compareActive = false;
    var compareSliderEl = null;
    var compareUpdateClip = null;
    var currentStep = null;
    var yearLabel;
    var mapLoadingIndicator;
    var mapContainerEl;
    var environmentMediaPanel;
    var afterBanMediaPanel;
    var conclusionMediaPanel;
    var mapLoadingCount = 0;
    var layerControl;
    var baseLayer;
    var mlFocusCenter = null;
    var mlFocusZoom = null;
    var mlAnchorCenter = null;
    var detectionsGeojsonData = null;
    var parcelsGeojsonData = null;

    // ── Parcel style ──
    var parcelStyle = {
        color: '#2196F3',
        weight: 2,
        opacity: 0.8,
        fillColor: '#2196F3',
        fillOpacity: 0.1
    };

    var parcelHighlightStyle = {
        color: '#ffd54f',
        weight: 3,
        opacity: 1,
        fillColor: '#ffd54f',
        fillOpacity: 0.25
    };

    var detectionStyle = {
        color: '#f44336',
        weight: 2,
        opacity: 0.8,
        fillColor: '#f44336',
        fillOpacity: 0.2
    };

    var countyBoundaryStyle = {
        color: '#ff0000',
        weight: 5,
        opacity: 1,
        fill: false
    };

    var butteFireStyle = {
        color: '#ff8f00',
        weight: 3,
        opacity: 0.95,
        fillColor: '#ff8f00',
        fillOpacity: 0.08
    };

    // ── Register a Planetary Computer mosaic for a given NAIP year ──
    function registerMosaic(year) {
        var body = {
            collections: ['naip'],
            'filter-lang': 'cql2-json',
            filter: {
                op: 'and',
                args: [
                    {
                        op: 's_intersects',
                        args: [
                            { property: 'geometry' },
                            { type: 'Polygon', coordinates: [PARCEL_BBOX] }
                        ]
                    },
                    { op: '>=', args: [{ property: 'datetime' }, year + '-01-01T00:00:00Z'] },
                    { op: '<=', args: [{ property: 'datetime' }, year + '-12-31T23:59:59Z'] }
                ]
            }
        };

        startMapLoading();
        return fetch(PC_BASE + '/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(function (r) {
            if (!r.ok) throw new Error('Mosaic register failed (' + r.status + ') for ' + year);
            return r.json();
        })
        .then(function (data) {
            if (!data.searchid) throw new Error('No searchid for ' + year);
            var tileUrl = PC_BASE + '/' + data.searchid +
                '/tiles/WebMercatorQuad/{z}/{x}/{y}?' + PC_TILE_PARAMS;
            return tileUrl;
        })
        .finally(function () {
            stopMapLoading();
        });
    }

    function updateMapLoadingIndicator() {
        if (!mapLoadingIndicator) return;
        var isVisible = mapLoadingCount > 0;
        mapLoadingIndicator.classList.toggle('visible', isVisible);
        mapLoadingIndicator.setAttribute('aria-hidden', isVisible ? 'false' : 'true');
    }

    function startMapLoading() {
        mapLoadingCount += 1;
        updateMapLoadingIndicator();
    }

    function stopMapLoading() {
        mapLoadingCount = Math.max(0, mapLoadingCount - 1);
        updateMapLoadingIndicator();
    }

    function clearLayerLoadingState(layer) {
        if (!layer) return;
        if (layer.__mapSpinnerLoading) {
            layer.__mapSpinnerLoading = false;
            stopMapLoading();
        }
    }

    function updateEnvironmentMediaPanel(stepId) {
        if (!mapContainerEl || !environmentMediaPanel || !afterBanMediaPanel || !conclusionMediaPanel) return;
        var isEnvironmentStep = stepId === 'environment';
        var isAfterBanStep = stepId === 'after-2018';
        var isConclusionStep = stepId === 'conclusion';
        mapContainerEl.classList.toggle('environment-media-active', isEnvironmentStep);
        mapContainerEl.classList.toggle('after-ban-media-active', isAfterBanStep);
        mapContainerEl.classList.toggle('conclusion-media-active', isConclusionStep);
        environmentMediaPanel.setAttribute('aria-hidden', isEnvironmentStep ? 'false' : 'true');
        afterBanMediaPanel.setAttribute('aria-hidden', isAfterBanStep ? 'false' : 'true');
        conclusionMediaPanel.setAttribute('aria-hidden', isConclusionStep ? 'false' : 'true');
    }

    function bindLayerLoadingEvents(layer) {
        if (!layer || typeof layer.on !== 'function' || layer.__mapSpinnerBound) return;
        layer.__mapSpinnerBound = true;
        layer.__mapSpinnerLoading = false;

        layer.on('loading', function () {
            if (layer.__mapSpinnerLoading) return;
            layer.__mapSpinnerLoading = true;
            startMapLoading();
        });

        var markDone = function () {
            if (!layer.__mapSpinnerLoading) return;
            layer.__mapSpinnerLoading = false;
            stopMapLoading();
        };

        layer.on('load', markDone);
        layer.on('tileerror', markDone);
        layer.on('remove', markDone);
    }

    function logMapView(reason) {
        if (!map) return;
        var center = map.getCenter();
        console.log(
            '[MAP VIEW]',
            reason,
            'step=' + (currentStep || 'none'),
            'zoom=' + map.getZoom(),
            'center=' + center.lat.toFixed(5) + ',' + center.lng.toFixed(5)
        );
    }

    function refreshLayerControl() {
        if (!map || !baseLayer) return;

        var overlayMaps = {};
        if (layers['naip-2014']) overlayMaps['NAIP 2014'] = layers['naip-2014'];
        if (layers['naip-2016']) overlayMaps['NAIP 2016'] = layers['naip-2016'];
        if (layers['naip-2018']) overlayMaps['NAIP 2018'] = layers['naip-2018'];
        if (parcelsLayer) overlayMaps['Cannabis Parcels'] = parcelsLayer;
        if (detectionsLayer) overlayMaps['2016 Detected Farms'] = detectionsLayer;
        if (butteFireLayer) overlayMaps['2015 Butte Fire Perimeter'] = butteFireLayer;

        if (layerControl) map.removeControl(layerControl);
        layerControl = L.control.layers({ 'OpenStreetMap': baseLayer }, overlayMaps, {
            position: 'topright', collapsed: true
        }).addTo(map);
    }

    function collectCoordinatePairs(coords, out) {
        if (!Array.isArray(coords)) return;

        if (
            coords.length >= 2 &&
            typeof coords[0] === 'number' &&
            typeof coords[1] === 'number'
        ) {
            out.push([coords[0], coords[1]]);
            return;
        }

        coords.forEach(function (child) {
            collectCoordinatePairs(child, out);
        });
    }

    function parseAreaM2(feature) {
        if (!feature || !feature.properties || !feature.properties.description) return 0;
        var desc = String(feature.properties.description);
        var m = desc.match(/~\s*([0-9]+(?:\.[0-9]+)?)\s*m²/i);
        if (!m) return 0;
        var v = parseFloat(m[1]);
        return Number.isFinite(v) ? v : 0;
    }

    function pointInRing(lng, lat, ring) {
        if (!Array.isArray(ring) || ring.length < 3) return false;
        var inside = false;

        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            var xi = ring[i][0];
            var yi = ring[i][1];
            var xj = ring[j][0];
            var yj = ring[j][1];

            var intersects = ((yi > lat) !== (yj > lat)) &&
                (lng < ((xj - xi) * (lat - yi) / ((yj - yi) || 1e-12)) + xi);
            if (intersects) inside = !inside;
        }

        return inside;
    }

    function pointInPolygonRings(lng, lat, polygonRings) {
        if (!Array.isArray(polygonRings) || !polygonRings.length) return false;

        if (!pointInRing(lng, lat, polygonRings[0])) return false;
        for (var i = 1; i < polygonRings.length; i++) {
            if (pointInRing(lng, lat, polygonRings[i])) return false;
        }
        return true;
    }

    function pointInGeometry(lng, lat, geometry) {
        if (!geometry || !geometry.type || !geometry.coordinates) return false;

        if (geometry.type === 'Polygon') {
            return pointInPolygonRings(lng, lat, geometry.coordinates);
        }

        if (geometry.type === 'MultiPolygon') {
            for (var i = 0; i < geometry.coordinates.length; i++) {
                if (pointInPolygonRings(lng, lat, geometry.coordinates[i])) return true;
            }
        }

        return false;
    }

    function isCentroidInsideAnyParcel(centroid, parcelsGeojson) {
        if (!centroid || !parcelsGeojson || !Array.isArray(parcelsGeojson.features)) return false;
        var lat = centroid[0];
        var lng = centroid[1];

        for (var i = 0; i < parcelsGeojson.features.length; i++) {
            var f = parcelsGeojson.features[i];
            if (f && f.geometry && pointInGeometry(lng, lat, f.geometry)) {
                return true;
            }
        }

        return false;
    }

    function getFeatureCentroidLatLng(feature) {
        if (!feature || !feature.geometry) return null;

        var coords = [];
        collectCoordinatePairs(feature.geometry.coordinates, coords);
        if (!coords.length) return null;

        var sumLng = 0;
        var sumLat = 0;

        coords.forEach(function (c) {
            sumLng += c[0];
            sumLat += c[1];
        });

        return [sumLat / coords.length, sumLng / coords.length];
    }

    function computeMlFocusFromDetections(geojson, parcelsGeojson, anchorCenter) {
        if (!geojson || !Array.isArray(geojson.features) || !geojson.features.length) {
            return null;
        }

        var centroids = [];
        geojson.features.forEach(function (feature) {
            var centroid = getFeatureCentroidLatLng(feature);
            if (!centroid) return;

            centroids.push({
                point: centroid,
                inParcel: isCentroidInsideAnyParcel(centroid, parcelsGeojson),
                areaM2: parseAreaM2(feature)
            });
        });

        if (!centroids.length) return null;

        var radiusDeg = 0.012;
        var radiusSq = radiusDeg * radiusDeg;
        var anchorLimitDeg = 0.08;
        var anchorLimitSq = anchorLimitDeg * anchorLimitDeg;
        var best = null;

        centroids.forEach(function (seed) {
            if (anchorCenter) {
                var sLat = seed.point[0] - anchorCenter[0];
                var sLng = seed.point[1] - anchorCenter[1];
                if ((sLat * sLat) + (sLng * sLng) > anchorLimitSq) return;
            }

            var count = 0;
            var inParcelCount = 0;
            var sumLat = 0;
            var sumLng = 0;
            var areaInParcel = 0;

            centroids.forEach(function (p) {
                var dLat = p.point[0] - seed.point[0];
                var dLng = p.point[1] - seed.point[1];
                if ((dLat * dLat) + (dLng * dLng) <= radiusSq) {
                    count += 1;
                    sumLat += p.point[0];
                    sumLng += p.point[1];
                    if (p.inParcel) {
                        inParcelCount += 1;
                        areaInParcel += p.areaM2;
                    }
                }
            });

            var score = (inParcelCount * 3) + count + (areaInParcel / 6000);

            if (!best || score > best.score) {
                best = {
                    score: score,
                    count: count,
                    inParcelCount: inParcelCount,
                    center: [sumLat / count, sumLng / count]
                };
            }
        });

        if (!best) return null;

        if (anchorCenter && best.inParcelCount < 2) {
            return null;
        }

        var focusCount = best.inParcelCount > 0 ? best.inParcelCount : best.count;
        var zoom = 15;
        if (focusCount >= 6) zoom = 16;
        if (focusCount >= 12) zoom = 17;

        return {
            center: best.center,
            zoom: zoom
        };
    }

    function recomputeMlFocus() {
        if (!detectionsGeojsonData) return;
        var mlFocus = computeMlFocusFromDetections(
            detectionsGeojsonData,
            parcelsGeojsonData,
            mlAnchorCenter
        );
        if (!mlFocus) {
            mlFocusCenter = null;
            mlFocusZoom = null;
            return;
        }

        mlFocusCenter = mlFocus.center;
        mlFocusZoom = mlFocus.zoom;

        if (currentStep === 'ml' && mlFocusCenter) {
            map.flyTo(mlFocusCenter, mlFocusZoom || 15, { duration: 1.0 });
        }
    }

    // ── Initialize Map ──
    function initMap() {
        map = L.map('map', {
            center: MAP_CENTER,
            zoom: MAP_ZOOM,
            minZoom: 8,
            maxBoundsViscosity: 1.0,
            zoomControl: true,
            scrollWheelZoom: true,
            preferCanvas: true
        });

        // Base layer: OpenStreetMap
        baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(map);
        bindLayerLoadingEvents(baseLayer);

        yearLabel = document.getElementById('current-year-label');
        mapLoadingIndicator = document.getElementById('map-loading-indicator');
        mapContainerEl = document.getElementById('map-container');
        environmentMediaPanel = document.getElementById('environment-media-panel');
        afterBanMediaPanel = document.getElementById('after-ban-media-panel');
        conclusionMediaPanel = document.getElementById('conclusion-media-panel');
        updateMapLoadingIndicator();
        updateEnvironmentMediaPanel(null);

        map.on('zoomend', function () {
            logMapView('zoomend');
        });

        // Scale bar (mi + km)
        L.control.scale().addTo(map);

        // Create custom panes for each NAIP year (needed for clip-based compare)
        var years = ['2014', '2016', '2018'];
        years.forEach(function (year, i) {
            var paneName = 'naip-' + year;
            map.createPane(paneName);
            map.getPane(paneName).style.zIndex = 250 + i;
        });

        // Register Planetary Computer mosaics for each NAIP year
        var promises = years.map(function (year) {
            var opts = Object.assign({}, TILE_OPTIONS, { pane: 'naip-' + year });
            return registerMosaic(year).then(function (tileUrl) {
                console.log('Registered NAIP ' + year + ': ' + tileUrl);
                var layer = L.tileLayer(tileUrl, opts);
                bindLayerLoadingEvents(layer);
                layers['naip-' + year] = layer;
            }).catch(function (err) {
                console.error('Failed to register mosaic for ' + year + ':', err);
            });
        });

        // Once all mosaics are registered, add layer control and re-apply
        // the current step's layers in case the user scrolled to a NAIP step
        // before registration completed.
        Promise.all(promises).then(function () {
            refreshLayerControl();
            console.log('All NAIP mosaic layers ready');

            // Re-apply layers for the active step if it uses NAIP
            var activeStepEl = document.querySelector('.step.is-active');
            if (activeStepEl) {
                var layerStr = activeStepEl.getAttribute('data-layers');
                if (layerStr && layerStr.indexOf('naip-') !== -1) {
                    var layerNames = layerStr.split(',').map(function (n) { return n.trim(); });
                    setVisibleLayers(layerNames);
                    // Re-enable compare if needed
                    var isCompare = activeStepEl.getAttribute('data-compare') === 'true';
                    if (isCompare) {
                        var compareLeft = activeStepEl.getAttribute('data-compare-left') || 'naip-2014';
                        var compareRight = activeStepEl.getAttribute('data-compare-right') || 'naip-2018';
                        var compareLeftLabel = activeStepEl.getAttribute('data-compare-left-label');
                        var compareRightLabel = activeStepEl.getAttribute('data-compare-right-label');
                        enableCompare(compareLeft, compareRight, compareLeftLabel, compareRightLabel);
                    }
                }
            }
        });
    }

    // ── Load GeoJSON Data ──
    function loadData() {
        // Load cannabis parcels
        startMapLoading();
        fetch('js/parcels.geojson')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                parcelsGeojsonData = data;
                parcelsLayer = L.geoJSON(data, {
                    style: parcelStyle,
                    onEachFeature: function (feature, layer) {
                        var props = feature.properties;
                        var popup = '<div style="font-family:Inter,sans-serif;font-size:13px;">' +
                            '<strong>APN:</strong> ' + (props.APN || 'N/A') + '<br>' +
                            '<strong>Land Value:</strong> $' + (props.LANDVALUE ? props.LANDVALUE.toLocaleString() : 'N/A') + '<br>' +
                            '<strong>Net Value:</strong> $' + (props.NETVALUE ? props.NETVALUE.toLocaleString() : 'N/A') +
                            '</div>';
                        layer.bindPopup(popup);
                        layer.on('mouseover', function () { layer.setStyle(parcelHighlightStyle); });
                        layer.on('mouseout', function () { parcelsLayer.resetStyle(layer); });
                    }
                });
                refreshLayerControl();
                recomputeMlFocus();
            })
            .catch(function (err) {
                console.warn('Could not load parcels.geojson:', err);
            })
            .finally(function () {
                stopMapLoading();
            });

        // Load county boundary (inline data from county_boundary.js)
        if (typeof COUNTY_BOUNDARY_GEOJSON !== 'undefined') {
            countyBoundaryLayer = L.geoJSON(COUNTY_BOUNDARY_GEOJSON, {
                style: countyBoundaryStyle
            });
            var countyBounds = countyBoundaryLayer.getBounds();
            if (countyBounds && countyBounds.isValid()) {
                map.setMaxBounds(countyBounds);
                var countyMinZoom = map.getBoundsZoom(countyBounds);
                if (typeof countyMinZoom === 'number' && isFinite(countyMinZoom)) {
                    map.setMinZoom(Math.max(map.getMinZoom(), countyMinZoom));
                }
            }
            // Show immediately – intro is the first visible step
            countyBoundaryLayer.addTo(map);
            refreshLayerControl();
        }

        // Load 2015 Butte Fire perimeter
        startMapLoading();
        fetch('js/butte-fire.geojson')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                butteFireLayer = L.geoJSON(data, {
                    style: butteFireStyle,
                    onEachFeature: function (feature, layer) {
                        var props = feature.properties || {};
                        var popup = '<div style="font-family:Inter,sans-serif;font-size:13px;">' +
                            '<strong>2015 Butte Fire</strong><br>' +
                            '<strong>Incident #:</strong> ' + (props.INC_NUM || 'N/A') + '<br>' +
                            '<strong>GIS Acres:</strong> ' + (props.GIS_ACRES ? Number(props.GIS_ACRES).toLocaleString() : 'N/A') +
                            '</div>';
                        layer.bindPopup(popup);
                    }
                });
                if (currentStep === 'before-2014') {
                    var butteBounds = butteFireLayer.getBounds();
                    if (butteBounds && butteBounds.isValid()) {
                        map.flyToBounds(butteBounds.pad(0.08), { duration: 1.2, maxZoom: 13 });
                    }
                }
                refreshLayerControl();
            })
            .catch(function (err) {
                console.warn('Could not load butte-fire.geojson:', err);
            })
            .finally(function () {
                stopMapLoading();
            });

        // Load cannabis detections
        startMapLoading();
        fetch('js/detections.geojson')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                detectionsGeojsonData = data;
                recomputeMlFocus();

                detectionsLayer = L.geoJSON(data, {
                    style: detectionStyle,
                    onEachFeature: function (feature, layer) {
                        var popup = '<div style="font-family:Inter,sans-serif;font-size:13px;">' +
                            '<strong>2016 Detected Cannabis Farm</strong><br>' +
                            'Identified via ML semantic segmentation of NAIP imagery' +
                            '</div>';
                        layer.bindPopup(popup);
                    }
                });
                refreshLayerControl();
            })
            .catch(function (err) {
                console.warn('Could not load detections.geojson:', err);
            })
            .finally(function () {
                stopMapLoading();
            });
    }

    // ── Manage visible layers ──
    function setVisibleLayers(layerNames) {
        // Remove all NAIP layers
        Object.keys(layers).forEach(function (key) {
            if (map.hasLayer(layers[key])) {
                clearLayerLoadingState(layers[key]);
                map.removeLayer(layers[key]);
            }
        });

        // Remove vector overlays
        if (parcelsLayer && map.hasLayer(parcelsLayer)) {
            map.removeLayer(parcelsLayer);
        }
        if (detectionsLayer && map.hasLayer(detectionsLayer)) {
            map.removeLayer(detectionsLayer);
        }
        if (butteFireLayer && map.hasLayer(butteFireLayer)) {
            map.removeLayer(butteFireLayer);
        }

        // Remove compare slider
        removeCompare();

        if (!layerNames) {
            if (countyBoundaryLayer && !map.hasLayer(countyBoundaryLayer)) {
                countyBoundaryLayer.addTo(map);
            }
            return;
        }

        // Add requested layers
        var activeYear = null;
        layerNames.forEach(function (name) {
            if (name === 'county-boundary' && countyBoundaryLayer) {
                countyBoundaryLayer.addTo(map);
            } else if (name === 'parcels' && parcelsLayer) {
                parcelsLayer.addTo(map);
            } else if (name === 'detections') {
                if (detectionsLayer) detectionsLayer.addTo(map);
            } else if (name === 'butte-fire') {
                if (butteFireLayer) butteFireLayer.addTo(map);
            } else if (layers[name]) {
                layers[name].addTo(map);
                // Track the year for the label
                var match = name.match(/(\d{4})/);
                if (match) activeYear = match[1];
            }
        });

        if (countyBoundaryLayer && !map.hasLayer(countyBoundaryLayer)) {
            countyBoundaryLayer.addTo(map);
        }

        // Update year label
        if (activeYear && yearLabel) {
            yearLabel.textContent = 'NAIP ' + activeYear;
            yearLabel.classList.add('visible');
        } else if (yearLabel) {
            yearLabel.classList.remove('visible');
        }
    }

    // ── Custom side-by-side comparison using CSS clip ──
    function removeCompare() {
        if (compareSliderEl && compareSliderEl.parentNode) {
            compareSliderEl.parentNode.removeChild(compareSliderEl);
        }
        compareSliderEl = null;
        if (compareActive && compareUpdateClip) {
            map.off('move', compareUpdateClip);
            map.off('zoom', compareUpdateClip);
        }
        compareUpdateClip = null;
        compareActive = false;
        // Reset clip on all NAIP panes
        ['naip-2014', 'naip-2016', 'naip-2018'].forEach(function (paneName) {
            var pane = map.getPane(paneName);
            if (pane) { pane.style.clip = ''; pane.style.clipPath = ''; }
        });
    }

    function enableCompare(leftKey, rightKey, leftLabel, rightLabel) {
        if (!layers[leftKey] || !layers[rightKey]) return;

        var leftYearMatch = leftKey.match(/(\d{4})/);
        var rightYearMatch = rightKey.match(/(\d{4})/);
        var leftYearText = leftYearMatch ? leftYearMatch[1] : leftKey;
        var rightYearText = rightYearMatch ? rightYearMatch[1] : rightKey;
        var leftDisplayText = leftLabel || leftYearText;
        var rightDisplayText = rightLabel || rightYearText;

        // Ensure both layers are on the map
        if (!map.hasLayer(layers[leftKey])) layers[leftKey].addTo(map);
        if (!map.hasLayer(layers[rightKey])) layers[rightKey].addTo(map);

        compareActive = true;

        // Get pane DOM elements for clipping
        var leftPane = map.getPane(leftKey);
        var rightPane = map.getPane(rightKey);

        if (!leftPane || !rightPane) {
            console.error('Compare: panes not found for', leftKey, rightKey);
            return;
        }

        // Append slider to #map-container (NOT inside #map where Leaflet manages DOM)
        var wrapper = document.getElementById('map-container');
        compareSliderEl = document.createElement('div');
        compareSliderEl.className = 'compare-slider';
        compareSliderEl.innerHTML =
            '<div class="compare-handle">' +
              '<div class="compare-label compare-label-left">' + leftDisplayText + '</div>' +
              '<div class="compare-grip">&lsaquo; &rsaquo;</div>' +
              '<div class="compare-label compare-label-right">' + rightDisplayText + '</div>' +
            '</div>';
        wrapper.appendChild(compareSliderEl);

        var sliderPos = 0.5;
        var mapEl = document.getElementById('map');

        compareUpdateClip = function () {
            var mapRect = mapEl.getBoundingClientRect();
            var w = mapRect.width;
            var h = mapRect.height;
            var splitX = Math.round(w * sliderPos);

            // Compute clip in pane-local coords by compensating for pane transform
            // Use clip-path: inset() — modern, Firefox-compatible replacement for
            // the deprecated clip: rect() which Firefox has dropped.
            var leftRect = leftPane.getBoundingClientRect();
            var ldx = mapRect.left - leftRect.left;
            var ldy = mapRect.top  - leftRect.top;
            var leftRight = leftRect.width - (splitX + ldx);
            leftPane.style.clipPath = 'inset(' + ldy + 'px ' + leftRight + 'px ' + '0px ' + ldx + 'px)';

            var rightRect = rightPane.getBoundingClientRect();
            var rdx = mapRect.left - rightRect.left;
            var rdy = mapRect.top  - rightRect.top;
            var rightLeft = splitX + rdx;
            rightPane.style.clipPath = 'inset(' + rdy + 'px 0px 0px ' + rightLeft + 'px)';

            compareSliderEl.style.left = splitX + 'px';
        };

        compareUpdateClip();

        // Drag logic
        var dragging = false;

        function onPointerMove(e) {
            if (!dragging) return;
            var rect = wrapper.getBoundingClientRect();
            var clientX = e.touches ? e.touches[0].clientX : e.clientX;
            sliderPos = Math.max(0.05, Math.min(0.95, (clientX - rect.left) / rect.width));
            compareUpdateClip();
        }

        function onPointerUp() {
            dragging = false;
            map.dragging.enable();
            document.removeEventListener('mousemove', onPointerMove);
            document.removeEventListener('mouseup', onPointerUp);
            document.removeEventListener('touchmove', onPointerMove);
            document.removeEventListener('touchend', onPointerUp);
        }

        compareSliderEl.addEventListener('mousedown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dragging = true;
            map.dragging.disable();
            document.addEventListener('mousemove', onPointerMove);
            document.addEventListener('mouseup', onPointerUp);
        });

        compareSliderEl.addEventListener('touchstart', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dragging = true;
            map.dragging.disable();
            document.addEventListener('touchmove', onPointerMove, { passive: false });
            document.addEventListener('touchend', onPointerUp);
        });

        // Re-clip on map move/zoom (use named ref so we can cleanly remove)
        map.on('move', compareUpdateClip);
        map.on('zoom', compareUpdateClip);

        if (yearLabel) {
            yearLabel.textContent = leftDisplayText + ' <-- --> ' + rightDisplayText;
            yearLabel.classList.add('visible');
        }

        console.log('Compare slider enabled:', leftKey, 'vs', rightKey);

    }

    // ── Handle step activation ──
    function handleStepEnter(response) {
        var el = response.element;
        var stepId = el.getAttribute('data-step');
        var center = el.getAttribute('data-center');
        var zoom = parseInt(el.getAttribute('data-zoom'), 10) || MAP_ZOOM;
        var layerStr = el.getAttribute('data-layers');
        var isCompare = el.getAttribute('data-compare') === 'true';
        var compareLeft = el.getAttribute('data-compare-left') || 'naip-2014';
        var compareRight = el.getAttribute('data-compare-right') || 'naip-2018';
        var compareLeftLabel = el.getAttribute('data-compare-left-label');
        var compareRightLabel = el.getAttribute('data-compare-right-label');

        var targetCenter = null;
        var targetZoom = zoom;

        // Mark active step
        document.querySelectorAll('.step').forEach(function (s) {
            s.classList.remove('is-active');
        });
        el.classList.add('is-active');
        currentStep = stepId;
        updateEnvironmentMediaPanel(stepId);
        if (stepId !== 'ml') {
            mlAnchorCenter = null;
        }

        // Parse center coordinates
        if (center) {
            var parts = center.split(',');
            var lat = parseFloat(parts[0]);
            var lng = parseFloat(parts[1]);
            targetCenter = [lat, lng];
            if (stepId === 'ml') {
                mlAnchorCenter = [lat, lng];
                mlFocusCenter = null;
                mlFocusZoom = null;
                recomputeMlFocus();
            }
        }

        // For the ML section, prefer a computed cluster focus if available.
        if (stepId === 'ml' && mlFocusCenter) {
            targetCenter = mlFocusCenter;
            targetZoom = mlFocusZoom || Math.max(zoom, 15);
        }

        // For the ML section, back off one zoom step to avoid over-zooming.
        if (stepId === 'ml') {
            targetZoom = Math.max(0, targetZoom - 1);
        }

        var layerNames = layerStr ? layerStr.split(',').map(function (name) {
            return name.trim();
        }) : null;

        var shouldFitParcels =
            stepId === 'peak-2016' &&
            parcelsLayer;

        var shouldFitButte =
            stepId === 'before-2014' &&
            layerNames &&
            layerNames.indexOf('butte-fire') !== -1 &&
            butteFireLayer;

        if (shouldFitParcels) {
            var parcelsBounds = parcelsLayer.getBounds();
            if (parcelsBounds && parcelsBounds.isValid()) {
                map.flyToBounds(parcelsBounds.pad(0.02), {
                    duration: 1.2,
                    maxZoom: targetZoom
                });
                map.once('moveend', function () {
                    logMapView('step:' + stepId + ':parcels-fit');
                });
            }
        } else if (shouldFitButte) {
            var butteBounds = butteFireLayer.getBounds();
            if (butteBounds && butteBounds.isValid()) {
                map.flyToBounds(butteBounds.pad(0.08), {
                    duration: 1.2,
                    maxZoom: targetZoom
                });
                map.once('moveend', function () {
                    logMapView('step:' + stepId + ':butte-fit');
                });
            }
        } else if (targetCenter) {
            map.flyTo(targetCenter, targetZoom, { duration: 1.2 });
            map.once('moveend', function () {
                logMapView('step:' + stepId);
            });
        }

        // Parse and set layers
        setVisibleLayers(layerNames);

        // Enable compare mode if requested
        if (isCompare) {
            enableCompare(compareLeft, compareRight, compareLeftLabel, compareRightLabel);
        }
    }

    // ── Initialize Scrollama ──
    function initScrollama() {
        var scroller = scrollama();

        // On mobile (stacked layout), the map occupies the top ~55vh and story
        // cards sit below it. Use a lower offset so steps trigger when the top
        // of the card enters the viewport rather than waiting for the midpoint.
        var scrollamaOffset = window.innerWidth <= 900 ? 0.85 : 0.5;

        scroller
            .setup({
                step: '.step',
                offset: scrollamaOffset,
                progress: false,
                debug: false
            })
            .onStepEnter(handleStepEnter);

        // Handle window resize
        window.addEventListener('resize', function () {
            scroller.resize();
            map.invalidateSize();
        });
    }

    function resetScrollToStart() {
        if (typeof history !== 'undefined' && 'scrollRestoration' in history) {
            history.scrollRestoration = 'manual';
        }

        window.scrollTo(0, 0);
        requestAnimationFrame(function () {
            window.scrollTo(0, 0);
        });
    }

    function initScrollOverflowIndicators() {
        var wrappers = document.querySelectorAll('.step-content-wrapper');
        wrappers.forEach(function (wrapper) {
            var el = wrapper.querySelector('.step-content');
            if (!el) return;
            function update() {
                var overflows = el.scrollHeight > el.clientHeight + 4;
                var atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
                wrapper.classList.toggle('has-overflow', overflows && !atBottom);
            }
            update();
            el.addEventListener('scroll', update);
            window.addEventListener('resize', update);
        });
    }

    // ── Boot ──
    document.addEventListener('DOMContentLoaded', function () {
        resetScrollToStart();
        initMap();
        loadData();
        initScrollama();
        initScrollOverflowIndicators();
    });

})();
