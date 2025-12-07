(function(window) {
    'use strict';

    class BreakoutDistanceChartWidget {
        constructor(options = {}) {
            this.container = typeof options.chartContainer === 'string'
                ? document.getElementById(options.chartContainer)
                : options.chartContainer;
            this.assetSymbol = options.assetSymbol || '';
            this.assetId = options.assetId || '';
            this.timeframe = options.timeframe || '1m';
            this.hours = options.hours || 6;
            this.refreshMs = options.refreshMs || 5000;
            this.rangeVisibility = {
                asia: true,
                london: true,
                us: true,
                ...(options.rangeVisibility || {}),
            };
            this.dataStatusBadge = this._resolveElement(options.dataStatusBadge);
            this.dataStatusText = this._resolveElement(options.dataStatusText);

            this.infoElements = {};
            const infoSelectors = options.infoSelectors || {};
            for (const [key, selector] of Object.entries(infoSelectors)) {
                this.infoElements[key] = this._resolveElement(selector);
            }

            this.currentCandles = [];
            this.priceLines = {};
            this.chart = null;
            this.candlestickSeries = null;
            this.volumeSeries = null;
            this.refreshInterval = null;
            this.initialized = false;
            this.activeRequestToken = 0;
            this.lastAssetKey = `${this.assetSymbol}|${this.assetId}`;

            this.colors = {
                asia: { fill: 'rgba(255, 193, 7, 0.15)', line: '#ffc107' },
                london: { fill: 'rgba(59, 130, 246, 0.15)', line: '#3b82f6' },
                us: { fill: 'rgba(34, 197, 94, 0.15)', line: '#22c55e' },
                breakoutLong: '#22c55e',
                breakoutShort: '#ef4444',
                rangeHigh: '#fbbf24',
                rangeLow: '#fb923c',
                volumeUp: '#4caf50',
                volumeDown: '#eb4034',
            };

            this.volumeScaleMargins = {
                top: 0.8,    // Price chart uses top 80%
                bottom: 0,   // Volume histogram uses bottom 20%
            };

            this.resizeHandler = this._handleResize.bind(this);
        }

        _resolveElement(target) {
            if (!target) return null;
            if (target instanceof HTMLElement) return target;
            return document.querySelector(target);
        }

        init() {
            if (!this.container || this.initialized) return;
            this.initialized = true;
            this.showLoading();
            window.addEventListener('resize', this.resizeHandler);
            this.loadChartData();
        }

        destroy() {
            this.stopAutoRefresh();
            window.removeEventListener('resize', this.resizeHandler);
            if (this.chart && this.container) {
                this.chart.remove();
                this.container.innerHTML = '';
            }
            this.chart = null;
            this.candlestickSeries = null;
            this.volumeSeries = null;
            this.priceLines = {};
            this.currentCandles = [];
            this.initialized = false;
        }

        _handleResize() {
            if (this.chart && this.container) {
                this.chart.resize(this.container.offsetWidth, this.container.offsetHeight);
            }
        }

        setAsset(symbol, assetId) {
            this.assetSymbol = symbol;
            this.assetId = assetId;
            this.currentCandles = [];

            this._resetChartState();

            this.lastAssetKey = `${symbol}|${assetId}`;
            this.activeRequestToken++;

            // Show loading state so the user sees the asset switch immediately
            if (this.chart) {
                this.showLoading();
            }
        }

        setHours(hours) {
            this.hours = hours;
        }

        setRangeVisibility(rangeKey, isVisible) {
            this.rangeVisibility[rangeKey] = isVisible;
            this.refresh();
        }

        _resetChartState() {
            // Reset chart visuals immediately when switching assets to avoid stale views
            if (this.candlestickSeries) {
                this.candlestickSeries.setData([]);
            }
            
            if (this.volumeSeries) {
                this.volumeSeries.setData([]);
            }

            for (const key in this.priceLines) {
                try {
                    this.candlestickSeries?.removePriceLine(this.priceLines[key]);
                } catch (e) {}
                delete this.priceLines[key];
            }

            // Fully recreate the chart container on the next load to avoid detached canvases
            if (this.chart) {
                try {
                    this.chart.remove();
                } catch (e) {}
                this.chart = null;
                this.candlestickSeries = null;
                this.volumeSeries = null;
            }
        }

        refresh() {
            this.loadChartData();
        }

        startAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
            }
            this.refreshInterval = setInterval(() => this.loadChartData(), this.refreshMs);
        }

        stopAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        }

        resizeToContainer() {
            this._handleResize();
        }

        async loadChartData() {
            if (!this.container || !this.assetId || !this.assetSymbol) {
                return;
            }

            const requestToken = ++this.activeRequestToken;
            const expectedAssetKey = `${this.assetSymbol}|${this.assetId}`;
            const firstLoad = !this.chart;
            if (firstLoad) {
                this.showLoading();
            }

            try {
                const candlesPromise = fetch(`/fiona/api/breakout-distance-candles?asset_id=${this.assetId}&timeframe=${this.timeframe}&window=${this.hours}&force_refresh=1`);
                const contextPromise = fetch(`/fiona/api/chart/${this.assetSymbol}/breakout-context`);
                const rangesPromise = fetch(`/fiona/api/chart/${this.assetSymbol}/session-ranges?hours=${this.hours}`);

                const [candlesRes, contextRes] = await Promise.all([candlesPromise, contextPromise]);

                // Ignore stale responses if the asset has changed mid-flight
                if (requestToken !== this.activeRequestToken || expectedAssetKey !== this.lastAssetKey) {
                    return;
                }

                const candlesData = await candlesRes.json();
                const contextData = await contextRes.json();
                let rangesData = { success: false };

                try {
                    const rangesRes = await rangesPromise;
                    rangesData = await rangesRes.json();
                } catch (rangeError) {
                    console.warn('Session ranges fetch failed:', rangeError);
                }

                if (candlesData.success && candlesData.status) {
                    this.updateDataStatus(candlesData.status);
                } else {
                    this.updateDataStatus({ status: 'OFFLINE', error: candlesData.error });
                }

                const sanitizedCandles = this._sanitizeCandles(candlesData.candles);
                if (candlesData.success && sanitizedCandles.length > 0) {
                    if (!this.chart) {
                        this._createChart();
                    }
                    this._updateCandles(sanitizedCandles);
                    if (firstLoad && this.chart) {
                        this.chart.timeScale().fitContent();
                    }
                    this._setInfoText('candleCount', `${sanitizedCandles.length} Candles`);
                } else {
                    if (firstLoad) {
                        this.showError(candlesData.error || 'Keine Kerzen-Daten verfügbar');
                    }
                    return;
                }

                if (contextData.success) {
                    this._updateInfoPanel(contextData);
                }

                if (rangesData.success && rangesData.ranges) {
                    this._drawSessionRanges(rangesData.ranges, contextData);
                }

                if (contextData.success) {
                    this._drawBreakoutContext(contextData);
                }
            } catch (error) {
                this.updateDataStatus({ status: 'OFFLINE', error: error.message });
                if (firstLoad) {
                    this.showError('Fehler beim Laden der Chart-Daten');
                }
            }
        }

        _createChart() {
            if (!this.container) return;
            this.container.innerHTML = '';
            this.chart = LightweightCharts.createChart(this.container, {
                width: this.container.offsetWidth,
                height: this.container.offsetHeight,
                layout: {
                    background: { type: 'solid', color: '#2d3239' },
                    textColor: '#e9ecef',
                },
                grid: {
                    vertLines: { color: 'rgba(255, 255, 255, 0.1)' },
                    horzLines: { color: 'rgba(255, 255, 255, 0.1)' },
                },
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal,
                },
                rightPriceScale: {
                    borderColor: '#484f58',
                },
                timeScale: {
                    borderColor: '#484f58',
                    timeVisible: true,
                    secondsVisible: false,
                },
            });

            this.candlestickSeries = this.chart.addCandlestickSeries({
                upColor: '#ef4444',
                downColor: '#22c55e',
                borderUpColor: '#ef4444',
                borderDownColor: '#22c55e',
                wickUpColor: '#ef4444',
                wickDownColor: '#22c55e',
            });

            // Add volume histogram series
            this.volumeSeries = this.chart.addHistogramSeries({
                priceFormat: { type: 'volume' },
                priceScaleId: '',
                scaleMargins: this.volumeScaleMargins,
            });

            this.priceLines = {};
        }

        _sanitizeCandles(candles) {
            if (!Array.isArray(candles)) return [];
            const validCandles = [];
            for (const candle of candles) {
                if (!candle) continue;
                const requiredFields = ['time', 'open', 'high', 'low', 'close'];
                if (requiredFields.some(key => candle[key] === null || candle[key] === undefined)) {
                    continue;
                }

                const normalized = {
                    time: Number(candle.time),
                    open: Number(candle.open),
                    high: Number(candle.high),
                    low: Number(candle.low),
                    close: Number(candle.close),
                };

                if (Object.values(normalized).some(value => Number.isNaN(value))) {
                    continue;
                }

                if (candle.volume !== null && candle.volume !== undefined) {
                    const volume = Number(candle.volume);
                    if (!Number.isNaN(volume)) {
                        normalized.volume = volume;
                    }
                }

                if (candle.complete === false) {
                    normalized.complete = false;
                }

                validCandles.push(normalized);
            }
            return validCandles;
        }

        _updateCandles(newCandles) {
            if (!newCandles || !newCandles.length || !this.candlestickSeries) {
                return;
            }

            if (!this.currentCandles.length) {
                this.currentCandles = [...newCandles];
            } else {
                const candleMap = new Map(this.currentCandles.map(c => [c.time, c]));
                for (const candle of newCandles) {
                    candleMap.set(candle.time, candle);
                }
                this.currentCandles = Array.from(candleMap.values()).sort((a, b) => a.time - b.time);
            }

            this.candlestickSeries.setData(this.currentCandles);
            
            // Update volume histogram if series exists
            if (this.volumeSeries) {
                const volumeData = this.currentCandles
                    .filter(c => c.volume !== null && c.volume !== undefined)
                    .map(c => ({
                        time: c.time,
                        value: c.volume,
                        color: c.close >= c.open ? this.colors.volumeUp : this.colors.volumeDown
                    }));
                
                if (volumeData.length > 0) {
                    this.volumeSeries.setData(volumeData);
                }
            }
        }

        updateDataStatus(statusData) {
            if (!this.dataStatusBadge || !this.dataStatusText) return;

            this.dataStatusBadge.classList.remove('live', 'poll', 'cached', 'offline');

            const status = (statusData.status || 'OFFLINE').toUpperCase();
            let cssClass = 'offline';
            let displayText = status;
            let tooltip = 'Datenstatus';

            switch (status) {
                case 'LIVE':
                    cssClass = 'live';
                    displayText = 'LIVE';
                    tooltip = 'Echtzeit-Stream aktiv';
                    break;
                case 'POLL':
                    cssClass = 'poll';
                    displayText = 'POLL';
                    tooltip = 'Fallback: REST-Polling';
                    break;
                case 'CACHED':
                    cssClass = 'cached';
                    displayText = 'CACHE';
                    tooltip = 'Daten aus Redis-Cache';
                    break;
                default:
                    cssClass = 'offline';
                    displayText = 'OFFLINE';
                    tooltip = statusData.error || 'Keine Daten / Verbindungsfehler';
                    break;
            }

            this.dataStatusBadge.classList.add(cssClass);
            this.dataStatusText.textContent = displayText;
            this.dataStatusBadge.title = tooltip;
        }

        _drawSessionRanges(ranges, context) {
            if (!this.candlestickSeries) return;
            for (const key in this.priceLines) {
                if (key.startsWith('range_')) {
                    try {
                        this.candlestickSeries.removePriceLine(this.priceLines[key]);
                    } catch (e) {}
                    delete this.priceLines[key];
                }
            }

            const phaseMapping = {
                'ASIA_RANGE': 'asia',
                'LONDON_CORE': 'london',
                'PRE_US_RANGE': 'us',
                'US_CORE_TRADING': 'us',
            };

            for (const [phase, rangeData] of Object.entries(ranges)) {
                const rangeKey = phaseMapping[phase];
                if (!rangeKey || !this.rangeVisibility[rangeKey]) continue;
                if (!rangeData.is_valid || !rangeData.high || !rangeData.low) continue;

                const color = this.colors[rangeKey];
                this.priceLines[`range_${phase}_high`] = this.candlestickSeries.createPriceLine({
                    price: rangeData.high,
                    color: color.line,
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `${phase} High`,
                });

                this.priceLines[`range_${phase}_low`] = this.candlestickSeries.createPriceLine({
                    price: rangeData.low,
                    color: color.line,
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `${phase} Low`,
                });
            }

            // Only draw range high/low lines; background zones removed for clarity
        }

        _drawBreakoutContext(context) {
            if (!this.candlestickSeries) return;

            for (const key in this.priceLines) {
                if (!key.startsWith('range_')) {
                    try {
                        this.candlestickSeries.removePriceLine(this.priceLines[key]);
                    } catch (e) {}
                    delete this.priceLines[key];
                }
            }

            if (!context.range_high || !context.range_low) return;

            this.priceLines['range_high'] = this.candlestickSeries.createPriceLine({
                price: context.range_high,
                color: this.colors.rangeHigh,
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: 'Range High',
            });

            this.priceLines['range_low'] = this.candlestickSeries.createPriceLine({
                price: context.range_low,
                color: this.colors.rangeLow,
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: 'Range Low',
            });

            if (context.breakout_long_level) {
                this.priceLines['breakout_long'] = this.candlestickSeries.createPriceLine({
                    price: context.breakout_long_level,
                    color: this.colors.breakoutLong,
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: 'Breakout Long',
                });
            }

            if (context.breakout_short_level) {
                this.priceLines['breakout_short'] = this.candlestickSeries.createPriceLine({
                    price: context.breakout_short_level,
                    color: this.colors.breakoutShort,
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: 'Breakout Short',
                });
            }
        }

        _updateInfoPanel(context) {
            this._setInfoText('asset', this.assetSymbol || '--');
            this._setInfoText('phase', this._formatPhase(context.phase));
            this._setInfoText('referencePhase', this._formatPhase(context.reference_phase || '--'));
            this._setInfoText('rangeHigh', this._formatNumber(context.range_high));
            this._setInfoText('rangeLow', this._formatNumber(context.range_low));
            this._setInfoText('breakoutLong', this._formatNumber(context.breakout_long_level));
            this._setInfoText('breakoutShort', this._formatNumber(context.breakout_short_level));
            this._setInfoText('currentPrice', this._formatNumber(context.current_price));
            this._setInfoText('tickSize', context.tick_size || '--');
            this._setInfoText('distanceHigh', this._formatTicks(context.distance_to_high_ticks));
            this._setInfoText('distanceLow', this._formatTicks(context.distance_to_low_ticks));
            this._setInfoText('window', `${this.hours}h`);

            const statusEl = this.infoElements.status;
            if (statusEl) {
                if (context.is_above_range) {
                    statusEl.innerHTML = '<span class="status-badge above"><i class="bi bi-arrow-up-circle"></i> Oberhalb (Long)</span>';
                } else if (context.is_below_range) {
                    statusEl.innerHTML = '<span class="status-badge below"><i class="bi bi-arrow-down-circle"></i> Unterhalb (Short)</span>';
                } else {
                    statusEl.innerHTML = '<span class="status-badge inside"><i class="bi bi-arrows-collapse"></i> Innerhalb</span>';
                }
            }
        }

        _formatPhase(phase) {
            const phaseNames = {
                'ASIA_RANGE': 'Asia Range',
                'LONDON_CORE': 'London Core',
                'PRE_US_RANGE': 'Pre-US Range',
                'US_CORE_TRADING': 'US Core Trading',
                'OTHER': 'Other',
            };
            return phaseNames[phase] || phase || '--';
        }

        _formatNumber(value) {
            if (value === null || value === undefined || Number.isNaN(Number(value))) {
                return '--';
            }
            const num = Number(value);
            const absValue = Math.abs(num);
            let fractionDigits = 2;

            if (absValue < 10) {
                fractionDigits = 4;
            } else if (absValue < 100) {
                fractionDigits = 3;
            }

            return num.toFixed(fractionDigits);
        }

        _formatTicks(value) {
            if (value === null || value === undefined) return '-- Ticks';
            return `${value} Ticks`;
        }

        _setInfoText(key, value) {
            const el = this.infoElements[key];
            if (el) {
                el.textContent = value;
            }
        }

        showLoading() {
            if (!this.container) return;
            this.container.innerHTML = '<div class="chart-loading"><i class="bi bi-hourglass-split"></i></div>';
        }

        showError(message) {
            if (!this.container) return;
            this.container.innerHTML = `
                <div class="chart-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>${this._escapeHtml(message)}</p>
                    <button class="btn btn-sm btn-outline-light" type="button" data-chart-refresh="true">
                        <i class="bi bi-arrow-clockwise"></i> Erneut versuchen
                    </button>
                </div>
            `;
            const retryBtn = this.container.querySelector('[data-chart-refresh="true"]');
            if (retryBtn) {
                retryBtn.addEventListener('click', () => this.refresh());
            }
        }

        _escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    }

    window.BreakoutDistanceChartWidget = BreakoutDistanceChartWidget;
})(window);
