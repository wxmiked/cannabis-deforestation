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
    var compareActive = false;
    var compareSliderEl = null;
    var compareUpdateClip = null;
    var currentStep = null;
    var yearLabel;

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

        return fetch(PC_BASE + '/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.searchid) throw new Error('No searchid for ' + year);
            var tileUrl = PC_BASE + '/' + data.searchid +
                '/tiles/WebMercatorQuad/{z}/{x}/{y}?' + PC_TILE_PARAMS;
            return tileUrl;
        });
    }

    // ── Initialize Map ──
    function initMap() {
        map = L.map('map', {
            center: MAP_CENTER,
            zoom: MAP_ZOOM,
            minZoom: 8,
            zoomControl: true,
            scrollWheelZoom: true,
            preferCanvas: true
        });

        // Base layer: OpenStreetMap
        var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(map);

        yearLabel = document.getElementById('current-year-label');

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
                layers['naip-' + year] = L.tileLayer(tileUrl, opts);
            }).catch(function (err) {
                console.error('Failed to register mosaic for ' + year + ':', err);
            });
        });

        // Once all mosaics are registered, add layer control
        Promise.all(promises).then(function () {
            var overlayMaps = {};
            if (layers['naip-2014']) overlayMaps['NAIP 2014'] = layers['naip-2014'];
            if (layers['naip-2016']) overlayMaps['NAIP 2016'] = layers['naip-2016'];
            if (layers['naip-2018']) overlayMaps['NAIP 2018'] = layers['naip-2018'];

            // Add vector layers to control once they're loaded
            function addVectorControls() {
                if (parcelsLayer) overlayMaps['Cannabis Parcels'] = parcelsLayer;
                if (detectionsLayer) overlayMaps['2016 Detected Farms'] = detectionsLayer;
                L.control.layers({ 'OpenStreetMap': osm }, overlayMaps, {
                    position: 'topright', collapsed: true
                }).addTo(map);
            }

            // Wait a moment for GeoJSON to load, then add control
            setTimeout(addVectorControls, 1500);

            console.log('All NAIP mosaic layers ready');
        });
    }

    // ── Load GeoJSON Data ──
    function loadData() {
        // Load cannabis parcels
        fetch('js/parcels.geojson')
            .then(function (r) { return r.json(); })
            .then(function (data) {
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
            })
            .catch(function (err) {
                console.warn('Could not load parcels.geojson:', err);
            });

        // Load cannabis detections
        fetch('js/detections.geojson')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                detectionsLayer = L.geoJSON(data, {
                    style: detectionStyle,
                    onEachFeature: function (feature, layer) {
                        var popup = '<div style="font-family:Inter,sans-serif;font-size:13px;">' +
                            '<strong>2016 Detected Cannabis Farm</strong><br>' +
                            'Identified via ML semantic segmentation of NAIP imagery' +
                            '</div>';
                        layer.bindPopup(popup);
                    }
                }).addTo(map);
            })
            .catch(function (err) {
                console.warn('Could not load detections.geojson:', err);
            });
    }

    // ── Manage visible layers ──
    function setVisibleLayers(layerNames) {
        // Remove all NAIP layers
        Object.keys(layers).forEach(function (key) {
            if (map.hasLayer(layers[key])) {
                map.removeLayer(layers[key]);
            }
        });

        // Remove vector overlays
        if (parcelsLayer && map.hasLayer(parcelsLayer)) {
            map.removeLayer(parcelsLayer);
        }
        // detections layer stays visible at all times

        // Remove compare slider
        removeCompare();

        if (!layerNames) return;

        // Add requested layers
        var activeYear = null;
        layerNames.forEach(function (name) {
            if (name === 'parcels' && parcelsLayer) {
                parcelsLayer.addTo(map);
            } else if (name === 'detections') {
                // detections always visible, skip
            } else if (layers[name]) {
                layers[name].addTo(map);
                // Track the year for the label
                var match = name.match(/(\d{4})/);
                if (match) activeYear = match[1];
            }
        });

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
            if (pane) pane.style.clip = '';
        });
    }

    function enableCompare(leftKey, rightKey) {
        if (!layers[leftKey] || !layers[rightKey]) return;

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
              '<div class="compare-label compare-label-left">2014</div>' +
              '<div class="compare-grip">&lsaquo; &rsaquo;</div>' +
              '<div class="compare-label compare-label-right">2018</div>' +
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
            var leftRect = leftPane.getBoundingClientRect();
            var ldx = mapRect.left - leftRect.left;
            var ldy = mapRect.top  - leftRect.top;
            leftPane.style.clip = 'rect(' + ldy + 'px, ' + (splitX + ldx) + 'px, ' + (h + ldy) + 'px, ' + ldx + 'px)';

            var rightRect = rightPane.getBoundingClientRect();
            var rdx = mapRect.left - rightRect.left;
            var rdy = mapRect.top  - rightRect.top;
            rightPane.style.clip = 'rect(' + rdy + 'px, ' + (w + rdx) + 'px, ' + (h + rdy) + 'px, ' + (splitX + rdx) + 'px)';

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
            yearLabel.textContent = '2014 ← → 2018';
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

        // Mark active step
        document.querySelectorAll('.step').forEach(function (s) {
            s.classList.remove('is-active');
        });
        el.classList.add('is-active');
        currentStep = stepId;

        // Parse center coordinates
        if (center) {
            var parts = center.split(',');
            var lat = parseFloat(parts[0]);
            var lng = parseFloat(parts[1]);
            map.flyTo([lat, lng], zoom, { duration: 1.2 });
        }

        // Parse and set layers
        var layerNames = layerStr ? layerStr.split(',') : null;
        setVisibleLayers(layerNames);

        // Enable compare mode if requested
        if (isCompare) {
            enableCompare('naip-2014', 'naip-2018');
        }
    }

    // ── Initialize Scrollama ──
    function initScrollama() {
        var scroller = scrollama();

        scroller
            .setup({
                step: '.step',
                offset: 0.5,
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

    // ── Boot ──
    document.addEventListener('DOMContentLoaded', function () {
        initMap();
        loadData();
        initScrollama();
    });

})();
