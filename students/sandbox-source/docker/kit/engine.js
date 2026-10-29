/* Универсальный движок дашборда стенда OpenCode (/opt/viz/kit).
 *
 * Что делает: берёт window.__DATA__ (плоская таблица) и window.__SPEC__
 * (описание задачи: KPI, фильтры, показатели, графики), рисует страницу,
 * хранит настройки (CONFIG) и отбор (STATE), умеет сохранить автономный HTML.
 *
 * Чего тут намеренно нет:
 *  - внешних библиотек: графики — обычные DOM/SVG, поэтому нет Chart.js и
 *    его ResizeObserver, из-за которого headless Chromium зависал;
 *  - переходов на бесконечных таймерах, `transition: all`, анимаций ширины;
 *  - console.log (проверка страницы считает вывод в консоль ошибкой).
 *
 * Точки входа для автопроверки (/opt/viz/kit/verify_page.py):
 *   window.DASH = {spec, data, config, state, setFilter, select, applyConfig,
 *                  kpiValues, chartValues, reset}
 */
(function () {
  'use strict';

  var SPEC = window.__SPEC__ || {};
  var DATA = window.__DATA__ || { columns: [], rows: [] };
  var COLS = DATA.columns || [];
  var ROWS = DATA.rows || [];
  var IDX = {};
  COLS.forEach(function (c, i) { IDX[c] = i; });

  var ALL = '__all__';
  var TABLE_LIMIT = 100;
  var DIMS = SPEC.dimensions || {};
  var MEASURES = SPEC.measures || {};

  /* ─────────────────────────── мелкие помощники ─────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toNum(v) {
    if (typeof v === 'number') return isFinite(v) ? v : null;
    if (typeof v === 'string' && v.trim() !== '') {
      var n = Number(v.replace(',', '.'));
      return isFinite(n) ? n : null;
    }
    return null;
  }

  function cell(row, col) {
    var i = IDX[col];
    return i === undefined ? null : row[i];
  }

  function fmtNum(v, d) {
    if (v === null || v === undefined || typeof v !== 'number' || !isFinite(v)) return '—';
    d = (d === null || d === undefined) ? 1 : d;
    var neg = v < 0;
    var s = Math.abs(v).toFixed(d);
    if (d > 0) s = s.replace('.', ',');
    if (d === 0) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, '\u2009');
    return (neg ? '\u2212' : '') + s;
  }

  function fmtShare(v, d) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    return (v * 100).toFixed(d == null ? 1 : d).replace('.', ',') + '%';
  }

  function median(arr) {
    if (!arr.length) return null;
    var a = arr.slice().sort(function (x, y) { return x - y; });
    var m = Math.floor(a.length / 2);
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  }

  function uniq(values) {
    var seen = Object.create(null), out = [];
    values.forEach(function (v) {
      if (v === null || v === undefined || v === '') return;
      var k = String(v);
      if (!(k in seen)) { seen[k] = 1; out.push(v); }
    });
    return out;
  }

  function uniqueSorted(values) {
    var allNumeric = values.every(function (v) { return typeof v === 'number' || toNum(v) !== null; });
    if (allNumeric) return uniq(values).sort(function (a, b) { return Number(a) - Number(b); });
    return uniq(values).sort(function (a, b) { return String(a).localeCompare(String(b), 'ru'); });
  }

  /* ────────────────────────────── CONFIG / STATE ────────────────────────── */

  var CHART_IDS = (SPEC.charts || []).map(function (c) { return c.id; });

  function defaultsFor(chartSpec) {
    return {
      id: chartSpec.id,
      visible: true,
      title: chartSpec.title || chartSpec.id,
      dimension: chartSpec.dimension,
      measure: chartSpec.measure,
      type: chartSpec.type || 'hbar',
      overrides: { color: null, decimals: null, showLabels: null, sort: null, topN: null }
    };
  }

  function defaultConfig() {
    return {
      version: 5,
      global: {
        theme: 'light',
        accent: SPEC.accent || '#2f6f5e',
        decimals: SPEC.decimals == null ? 1 : SPEC.decimals,
        showLabels: true,
        title: SPEC.title || 'Дашборд'
      },
      charts: (SPEC.charts || []).map(defaultsFor)
    };
  }

  function defaultState() {
    return { filters: {}, selection: null, panel: false, tab: 'general' };
  }

  function isPlainObject(o) {
    return !!o && typeof o === 'object' && !Array.isArray(o) &&
      (Object.getPrototypeOf(o) === Object.prototype || Object.getPrototypeOf(o) === null);
  }

  var FORBIDDEN = ['__proto__', 'prototype', 'constructor'];

  function hasForbidden(o) {
    if (!isPlainObject(o)) return false;
    for (var i = 0; i < FORBIDDEN.length; i++) {
      if (Object.prototype.hasOwnProperty.call(o, FORBIDDEN[i])) return true;
    }
    return Object.keys(o).some(function (k) { return hasForbidden(o[k]); });
  }

  function normaliseConfig(raw) {
    var base = defaultConfig();
    if (!isPlainObject(raw)) return base;
    if (raw.version !== 5) return base;
    var g = raw.global;
    var out = defaultConfig();
    if (isPlainObject(g)) {
      if (g.theme === 'light' || g.theme === 'dark') out.global.theme = g.theme;
      if (typeof g.accent === 'string' && /^#[0-9a-fA-F]{6}$/.test(g.accent)) out.global.accent = g.accent;
      if (typeof g.decimals === 'number' && g.decimals >= 0 && g.decimals <= 4) out.global.decimals = g.decimals;
      if (typeof g.showLabels === 'boolean') out.global.showLabels = g.showLabels;
      if (typeof g.title === 'string' && g.title.length <= 200) out.global.title = g.title;
    }
    if (Array.isArray(raw.charts)) {
      raw.charts.forEach(function (c) {
        if (!isPlainObject(c)) return;
        var slot = null;
        for (var i = 0; i < out.charts.length; i++) if (out.charts[i].id === c.id) slot = out.charts[i];
        if (!slot) return;
        if (typeof c.visible === 'boolean') slot.visible = c.visible;
        if (typeof c.title === 'string' && c.title.length <= 200) slot.title = c.title;
        if (typeof c.dimension === 'string' && IDX[c.dimension] !== undefined) slot.dimension = c.dimension;
        if (typeof c.measure === 'string' && MEASURES[c.measure]) slot.measure = c.measure;
        var types = compatibleTypes(slot.dimension);
        if (typeof c.type === 'string' && types.indexOf(c.type) >= 0) slot.type = c.type;
        if (isPlainObject(c.overrides)) {
          var ov = c.overrides;
          if (ov.color === null || (typeof ov.color === 'string' && /^#[0-9a-fA-F]{6}$/.test(ov.color))) slot.overrides.color = ov.color;
          if (ov.decimals === null || (typeof ov.decimals === 'number' && ov.decimals >= 0 && ov.decimals <= 4)) slot.overrides.decimals = ov.decimals;
          if (ov.showLabels === null || typeof ov.showLabels === 'boolean') slot.overrides.showLabels = ov.showLabels;
          if (ov.sort === null || ov.sort === 'asc' || ov.sort === 'desc') slot.overrides.sort = ov.sort;
          if (ov.topN === null || (typeof ov.topN === 'number' && ov.topN >= 1 && ov.topN <= 500)) slot.overrides.topN = ov.topN;
        }
      });
    }
    return out;
  }

  function validateConfig(raw) {
    if (!isPlainObject(raw) || hasForbidden(raw)) return 'ожидался обычный объект без служебных ключей';
    if (raw.version !== 5) return 'version должен быть 5';
    var g = raw.global;
    if (!isPlainObject(g)) return 'нет блока global';
    if (g.theme !== 'light' && g.theme !== 'dark') return 'global.theme: light или dark';
    if (typeof g.accent !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(g.accent)) return 'global.accent: цвет вида #14704e';
    if (typeof g.decimals !== 'number' || g.decimals < 0 || g.decimals > 4) return 'global.decimals: целое 0–4';
    if (typeof g.showLabels !== 'boolean') return 'global.showLabels: true/false';
    if (raw.charts !== undefined) {
      if (!Array.isArray(raw.charts)) return 'charts: ожидался массив';
      var seen = Object.create(null);
      for (var i = 0; i < raw.charts.length; i++) {
        var c = raw.charts[i];
        if (!isPlainObject(c)) return 'charts[' + i + ']: ожидался объект';
        if (CHART_IDS.indexOf(c.id) < 0) return 'charts[' + i + '].id: неизвестный график';
        if (seen[c.id]) return 'charts: повторяется id ' + c.id;
        seen[c.id] = 1;
        if (c.visible !== undefined && typeof c.visible !== 'boolean') return 'charts[' + i + '].visible: true/false';
        if (c.overrides !== undefined && !isPlainObject(c.overrides)) return 'charts[' + i + '].overrides: ожидался объект';
      }
    }
    return '';
  }

  var savedConfig = normaliseConfig(window.__CONFIG__);
  var CONFIG = savedConfig;

  function defaultStateForSpec() {
    var st = defaultState();
    (SPEC.filters || []).forEach(function (f) {
      var values = uniqueSorted(ROWS.map(function (r) { return cell(r, f.column); }));
      if (f.default === 'last' && values.length) st.filters[f.id] = String(values[values.length - 1]);
      else st.filters[f.id] = ALL;
    });
    return st;
  }

  var STATE = defaultStateForSpec();
  (function restoreState(raw) {
    if (!isPlainObject(raw)) return;
    if (isPlainObject(raw.filters)) {
      (SPEC.filters || []).forEach(function (f) {
        var v = raw.filters[f.id];
        if (v === undefined) return;
        var allowed = uniqueSorted(ROWS.map(function (r) { return cell(r, f.column); })).map(String);
        if (v === ALL || allowed.indexOf(String(v)) >= 0) STATE.filters[f.id] = v;
      });
    }
    if (isPlainObject(raw.selection) && raw.selection.dimension && IDX[raw.selection.dimension] !== undefined) {
      STATE.selection = { dimension: String(raw.selection.dimension), value: raw.selection.value };
    } else if (raw.selection === null) {
      STATE.selection = null;
    }
  })(window.__STATE__);

  /* ───────────────────────────── отбор и агрегаты ───────────────────────── */

  function activeFilters() {
    var out = [];
    (SPEC.filters || []).forEach(function (f) {
      var v = STATE.filters[f.id];
      if (v === undefined || v === null || v === ALL) return;
      out.push({ column: f.column, value: v });
    });
    if (STATE.selection) out.push({ column: STATE.selection.dimension, value: STATE.selection.value });
    return out;
  }

  function filteredRows() {
    var act = activeFilters();
    if (!act.length) return ROWS;
    return ROWS.filter(function (r) {
      for (var i = 0; i < act.length; i++) {
        var v = cell(r, act[i].column);
        if (v === null || v === undefined) return false;
        if (String(v) !== String(act[i].value)) return false;
      }
      return true;
    });
  }

  function measureOf(key, chartCfg) {
    var m = MEASURES[key] || { label: key, column: key, agg: 'mean' };
    var copy = { label: m.label, column: m.column, agg: chartCfg && chartCfg.agg ? chartCfg.agg : (m.agg || 'mean'), equals: m.equals, unit: m.unit || '', share: !!m.share };
    if (m.share) copy.agg = 'share';
    return copy;
  }

  /* Возвращает {v, pos, den, n} — v это значение показателя для набора строк. */
  function compute(rows, m) {
    var n = rows.length;
    if (m.agg === 'count') return { v: n, pos: null, den: null, n: n };
    if (m.agg === 'count_distinct') {
      var seen = Object.create(null), k = 0;
      rows.forEach(function (r) { var v = cell(r, m.column); if (v === null || v === undefined || v === '') return; var s = String(v); if (!(s in seen)) { seen[s] = 1; k++; } });
      return { v: k, pos: null, den: null, n: n };
    }
    if (m.agg === 'share') {
      var pos = 0, den = 0;
      rows.forEach(function (r) {
        var v = cell(r, m.column);
        if (v === null || v === undefined) return;
        den++;
        if (String(v) === String(m.equals)) pos++;
      });
      return { v: den ? pos / den : null, pos: pos, den: den, n: n };
    }
    var vals = [];
    rows.forEach(function (r) { var v = toNum(cell(r, m.column)); if (v !== null) vals.push(v); });
    if (!vals.length) return { v: null, pos: null, den: null, n: n };
    var v2;
    if (m.agg === 'sum') v2 = vals.reduce(function (a, b) { return a + b; }, 0);
    else if (m.agg === 'first') v2 = vals[0];
    else if (m.agg === 'last') v2 = vals[vals.length - 1];
    else if (m.agg === 'min') v2 = Math.min.apply(null, vals);
    else if (m.agg === 'max') v2 = Math.max.apply(null, vals);
    else if (m.agg === 'median') v2 = median(vals);
    else v2 = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    return { v: v2, pos: null, den: null, n: n };
  }

  function isOrdered(dimension) {
    var d = DIMS[dimension];
    if (d && Array.isArray(d.order) && d.order.length) return true;
    if (d && typeof d.ordered === 'boolean') return d.ordered;
    var col = IDX[dimension];
    if (col === undefined) return false;
    var numeric = true, seen = 0;
    for (var i = 0; i < ROWS.length && seen < 60; i++) {
      var v = ROWS[i][col];
      if (v === null || v === undefined) continue;
      seen++;
      if (typeof v !== 'number') numeric = false;
    }
    return numeric && seen > 0;
  }

  function compatibleTypes(dimension) {
    return isOrdered(dimension) ? ['line', 'vbar', 'table'] : ['hbar', 'vbar', 'table'];
  }

  function chartTypeIsCompatible(type, dimension, topN) {
    if (compatibleTypes(dimension).indexOf(type) < 0) return false;
    if (type === 'line' && topN) return false;
    return true;
  }

  function dimensionLabel(dimension) {
    return (DIMS[dimension] && DIMS[dimension].label) || dimension;
  }

  /* Группировка: [{key, rows, value, pos, den, n}] */
  function buildGroups(rows, cfg) {
    var dim = cfg.dimension;
    var m = measureOf(cfg.measure, cfg);
    if (!MEASURES[cfg.measure] || (MEASURES[cfg.measure] || {}).agg === 'count') m.agg = m.agg === 'mean' ? 'mean' : m.agg;
    var buckets = Object.create(null), order = [];
    rows.forEach(function (r) {
      var raw = cell(r, dim);
      if (raw === null || raw === undefined || raw === '') return;
      var key = String(raw);
      if (!(key in buckets)) { buckets[key] = { key: key, raw: raw, rows: [] }; order.push(key); }
      buckets[key].rows.push(r);
    });

    var groups = order.map(function (key) {
      var b = buckets[key];
      var res = compute(b.rows, m);
      return { key: b.key, raw: b.raw, rows: b.rows, value: res.v, pos: res.pos, den: res.den, n: res.n };
    });

    var ordered = isOrdered(dim);
    var sort = cfg.sort || (ordered ? 'dim' : 'desc');
    var topN = cfg.topN == null ? null : Number(cfg.topN);

    if (ordered && (cfg.type === 'line' || sort === 'dim')) {
      // Явный порядок из spec («янв», «фев», …; «18–25», «26–35», …) важнее
      // алфавита: иначе месяцы идут авг → апр → дек.
      var explicit = (DIMS[dim] || {}).order;
      if (Array.isArray(explicit) && explicit.length) {
        groups.sort(function (a, b) {
          var ia = explicit.indexOf(String(a.raw));
          var ib = explicit.indexOf(String(b.raw));
          if (ia < 0) ia = explicit.length + 1;
          if (ib < 0) ib = explicit.length + 1;
          return ia - ib;
        });
      } else {
        groups.sort(function (a, b) {
          var an = toNum(a.raw), bn = toNum(b.raw);
          if (an !== null && bn !== null) return an - bn;
          return String(a.raw).localeCompare(String(b.raw), 'ru');
        });
      }
      return { groups: groups, m: m, ordered: ordered, rest: null, topN: null };
    }

    groups.sort(function (a, b) {
      var av = (a.value === null ? -Infinity : a.value), bv = (b.value === null ? -Infinity : b.value);
      if (av === bv) return String(a.raw).localeCompare(String(b.raw), 'ru');
      return sort === 'asc' ? av - bv : bv - av;
    });

    var rest = null;
    if (topN && groups.length > topN) {
      var head = groups.slice(0, topN);
      var tail = groups.slice(topN);
      if (cfg.rest && tail.length) {
        var tailRows = [];
        tail.forEach(function (g) { tailRows = tailRows.concat(g.rows); });
        if (cfg.rest === 'count') {
          rest = { key: 'Остальные (' + tail.length + ')', raw: null, rows: tailRows, value: tail.length, pos: null, den: null, n: tailRows.length, isRest: true };
        } else {
          var res = compute(tailRows, measureOf(cfg.measure, { agg: cfg.rest }));
          rest = { key: 'Остальные (' + tail.length + ')', raw: null, rows: tailRows, value: res.v, pos: res.pos, den: res.den, n: res.n, isRest: true };
        }
      }
      groups = head;
    } else if (topN && groups.length <= topN) {
      groups = groups.slice(0, topN);
    }
    return { groups: groups, m: m, ordered: ordered, rest: rest, topN: topN };
  }

  /* ────────────────────────────── форматирование ────────────────────────── */

  function decimalsFor(cfg) {
    if (cfg && cfg.overrides && cfg.overrides.decimals != null) return cfg.overrides.decimals;
    return CONFIG.global.decimals;
  }

  function showsLabels(cfg) {
    if (cfg && cfg.overrides && cfg.overrides.showLabels != null) return cfg.overrides.showLabels;
    return CONFIG.global.showLabels;
  }

  function colorFor(cfg) {
    if (cfg && cfg.overrides && cfg.overrides.color) return cfg.overrides.color;
    return CONFIG.global.accent;
  }

  function valueText(value, m, cfg, shareMode) {
    if (value === null || value === undefined) return '—';
    if (m.agg === 'share' || m.share) return fmtShare(value, decimalsFor(cfg));
    var d = m.agg === 'count' || m.agg === 'count_distinct' ? 0 : decimalsFor(cfg);
    var s = fmtNum(value, d);
    if (m.unit) s += ' ' + m.unit;
    return s;
  }

  /* ────────────────────────────────── DOM ───────────────────────────────── */

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'text') node.textContent = attrs[k];
        else if (k === 'html') node.innerHTML = attrs[k];
        else if (k.slice(0, 2) === 'on' && typeof attrs[k] === 'function') node.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  var root = document.getElementById('dash-root');
  var tipEl = document.getElementById('dash-tip');
  var panelEl = document.getElementById('dash-panel');

  function showTip(text, x, y) {
    if (!tipEl) return;
    tipEl.textContent = text;
    tipEl.hidden = false;
    var rect = tipEl.getBoundingClientRect();
    var left = Math.max(8, Math.min(window.innerWidth - rect.width - 8, x - rect.width / 2));
    var top = y - rect.height - 12;
    if (top < 8) top = y + 18;
    tipEl.style.left = left + 'px';
    tipEl.style.top = top + 'px';
  }

  function hideTip() { if (tipEl) tipEl.hidden = true; }

  function tipText(g, m, cfg) {
    var parts = [g.key + ': ' + valueText(g.value, m, cfg)];
    if (g.den !== null && g.den !== undefined) parts.push(g.pos + ' из ' + g.den + ' строк');
    else parts.push('строк: ' + g.n);
    return parts.join(' · ');
  }

  /* ──────────────────────────────── отрисовка ────────────────────────────── */

  function renderKpis(rows, container) {
    container.textContent = '';
    container.setAttribute('data-count', String((SPEC.kpis || []).length));
    (SPEC.kpis || []).forEach(function (k) {
      var m = {
        label: k.label, column: k.column || (k.agg && k.agg.column), agg: k.agg && k.agg.fn ? k.agg.fn : (k.agg || 'count'),
        equals: k.equals, unit: k.unit || '', share: !!k.share
      };
      if (m.agg === 'share') m.agg = 'share';
      var res = compute(rows, { column: m.column, agg: m.agg, equals: m.equals });
      var d = k.decimals == null ? CONFIG.global.decimals : k.decimals;
      if (m.agg === 'count' || m.agg === 'count_distinct') d = 0;
      var text = m.agg === 'share' ? fmtShare(res.v, d) : fmtNum(res.v, d);
      if (m.unit && res.v !== null && text.indexOf(m.unit) < 0) text += ' ' + m.unit;
      var sub = '';
      if (k.subBy && res.v !== null) {
        var best = null;
        rows.forEach(function (r) {
          var v = toNum(cell(r, k.column));
          if (v === null) return;
          if (!best || (m.agg === 'min' ? v < best.v : v > best.v)) best = { v: v, name: cell(r, k.subBy) };
        });
        if (best) sub = best.name;
      } else if (k.sub) {
        sub = k.sub;
      } else if (m.agg === 'share' && res.den) {
        sub = res.pos + ' из ' + res.den + ' строк';
      }
      if (!sub) sub = 'строк: ' + rows.length;
      container.appendChild(el('div', { class: 'dash-kpi' }, [
        el('div', { class: 'dash-kpi-label', text: k.label }),
        el('div', { class: 'dash-kpi-value', text: text }),
        el('div', { class: 'dash-kpi-sub', text: sub })
      ]));
    });
  }

  function emptyBox(text) {
    return el('div', { class: 'dash-chart-empty', text: text });
  }

  function renderHBar(groups, rest, m, cfg, body) {
    var all = groups.slice();
    if (rest) all.push(rest);
    if (!all.length) { body.appendChild(emptyBox('Нет данных для этого отбора.')); return; }

    var values = all.map(function (g) { return g.value === null ? 0 : g.value; });
    var hasNegative = values.some(function (v) { return v < 0; });
    var maxAbs = Math.max.apply(null, values.map(function (v) { return Math.abs(v); }));
    if (!maxAbs || maxAbs <= 0) maxAbs = 1;
    var color = colorFor(cfg);
    var labels = showsLabels(cfg);
    var dim = dimensionLabel(cfg.dimension);

    var wrap = el('div', { class: 'dash-hbar' + (all.length > 16 ? ' dense' : '') });
    all.forEach(function (g) {
      var v = g.value === null ? 0 : g.value;
      var frac = Math.abs(v) / maxAbs;
      var row = el('div', { class: 'dash-hrow', tabindex: '0', role: 'button', 'aria-label': g.key + ', ' + valueText(g.value, m, cfg) });
      row.appendChild(el('span', { class: 'dash-hlabel', title: g.key, text: g.key }));
      var track = el('span', { class: 'dash-htrack' });
      track.appendChild(el('span', { class: 'dash-zero' }));
      var bar = el('span', { class: 'dash-hbar-fill' });
      bar.style.background = color;
      if (!hasNegative) {
        // Все значения неотрицательные: шкала от нуля слева, без пустой половины.
        bar.style.left = '0';
        bar.style.width = (frac * 100) + '%';
      } else if (v < 0) {
        bar.style.left = (50 - frac * 50) + '%';
        bar.style.width = (frac * 50) + '%';
      } else {
        bar.style.left = '50%';
        bar.style.width = (frac * 50) + '%';
      }
      track.appendChild(bar);
      row.appendChild(track);
      if (labels) row.appendChild(el('span', { class: 'dash-hvalue', text: valueText(g.value, m, cfg) }));
      else row.appendChild(el('span', { class: 'dash-hvalue' }));

      var tip = tipText(g, m, cfg);
      row.addEventListener('mouseenter', function (e) { showTip(tip, e.clientX, e.clientY); });
      row.addEventListener('mousemove', function (e) { showTip(tip, e.clientX, e.clientY); });
      row.addEventListener('mouseleave', hideTip);
      row.addEventListener('focus', function () {
        var r = row.getBoundingClientRect();
        showTip(tip, r.left + r.width / 2, r.top);
      });
      row.addEventListener('blur', hideTip);
      if (g.rows.length && !g.isRest) {
        row.addEventListener('click', function () { toggleSelection(cfg.dimension, g.raw); });
        row.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSelection(cfg.dimension, g.raw); }
        });
      } else {
        row.removeAttribute('tabindex');
        row.removeAttribute('role');
      }
      wrap.appendChild(row);
    });

    if (hasNegative) wrap.classList.add('has-negative');
    body.appendChild(el('div', { class: 'dash-axis-note', text: dim }));
    body.appendChild(wrap);
  }

  function svgEl(name, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function niceTicks(min, max, count) {
    if (min === max) { min = Math.min(0, min); max = max === 0 ? 1 : max * 1.1; }
    var span = max - min;
    var step = Math.pow(10, Math.floor(Math.log10(span / Math.max(1, count))));
    var err = (span / Math.max(1, count)) / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var lo = Math.floor(min / step) * step;
    var hi = Math.ceil(max / step) * step;
    var out = [];
    for (var v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }

  function renderVBar(groups, rest, m, cfg, body) {
    var all = groups.slice();
    if (rest) all.push(rest);
    if (!all.length) { body.appendChild(emptyBox('Нет данных для этого отбора.')); return; }

    // viewBox уже карточки (420, а не 640): иначе в колонке ~320 px вся
    // типографика ужимается до 5 px и подписи не читаются.
    var W = 420, padL = 42, padR = 10, padT = 14;
    var longest = 0;
    all.forEach(function (g) { longest = Math.max(longest, String(g.key).length); });
    var bandW = (W - padL - padR) / Math.max(1, all.length);
    // Длинные подписи («начальное», «не указано») наезжают друг на друга в
    // узкой колонке, поэтому при 8+ символах подписываем под наклоном.
    var rotate = all.length > 14 || longest > 7 || longest * 6.2 > bandW * 0.78;
    var H = rotate ? 272 : 232, NB_PADB = rotate ? 62 : 30;
    var innerW = W - padL - padR, innerH = H - padT - NB_PADB;
    var values = all.map(function (g) { return g.value === null ? 0 : g.value; });
    var minV = Math.min.apply(null, values.concat([0]));
    var maxV = Math.max.apply(null, values.concat([0]));
    var ticks = niceTicks(minV, maxV, 5);
    var lo = ticks[0], hi = ticks[ticks.length - 1];
    var span = hi - lo || 1;
    function y(v) { return padT + innerH - ((v - lo) / span) * innerH; }

    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': cfg.title, class: 'dash-svg' });

    var tickFmt = function (t) {
      if (m.agg === 'share' || m.share) return fmtShare(t, 0);
      var d = (m.agg === 'count' || m.agg === 'count_distinct') ? 0 : (Math.abs(hi - lo) < 10 ? 1 : 0);
      return fmtNum(t, d);
    };
    ticks.forEach(function (t) {
      svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), class: 'dash-grid' }));
      var tx = svgEl('text', { x: padL - 8, y: y(t) + 4, class: 'dash-tick', 'text-anchor': 'end' });
      tx.textContent = tickFmt(t);
      svg.appendChild(tx);
    });
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), class: 'dash-zero-line' }));

    var band = innerW / all.length;
    var barW = Math.max(4, Math.min(46, band * 0.62));
    var color = colorFor(cfg);
    var labels = showsLabels(cfg);
    var skip = all.length > 40 ? 3 : all.length > 24 ? 2 : 1;

    all.forEach(function (g, i) {
      var v = g.value === null ? 0 : g.value;
      var cx = padL + band * i + band / 2;
      var top = Math.min(y(v), y(0));
      var hgt = Math.abs(y(v) - y(0));
      var rect = svgEl('rect', {
        x: cx - barW / 2, y: top, width: barW, height: Math.max(1, hgt),
        rx: Math.min(3, barW / 3), fill: color, class: 'dash-bar'
      });
      rect.setAttribute('tabindex', '0');
      rect.setAttribute('role', 'button');
      rect.setAttribute('aria-label', g.key + ', ' + valueText(g.value, m, cfg));
      var tip = tipText(g, m, cfg);
      rect.addEventListener('mouseenter', function (e) { showTip(tip, e.clientX, e.clientY); });
      rect.addEventListener('mouseleave', hideTip);
      rect.addEventListener('focus', function () { var r = rect.getBoundingClientRect(); showTip(tip, r.left + r.width / 2, r.top); });
      rect.addEventListener('blur', hideTip);
      if (g.rows.length && !g.isRest) {
        rect.addEventListener('click', function () { toggleSelection(cfg.dimension, g.raw); });
        rect.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSelection(cfg.dimension, g.raw); }
        });
      } else {
        rect.removeAttribute('tabindex');
        rect.removeAttribute('role');
      }
      svg.appendChild(rect);

      if (labels && all.length <= 24) {
        var lv = svgEl('text', { x: cx, y: v >= 0 ? top - 6 : top + hgt + 12, class: 'dash-val', 'text-anchor': 'middle' });
        lv.textContent = valueText(g.value, m, cfg);
        svg.appendChild(lv);
      }

      if (i % skip === 0) {
        var lab = svgEl('text', { x: cx, y: H - NB_PADB + 16, class: 'dash-cat', 'text-anchor': 'middle' });
        var text = g.key;
        if (text.length > 14) text = text.slice(0, 13) + '…';
        lab.textContent = text;
        if (rotate) lab.setAttribute('transform', 'rotate(-32 ' + cx + ' ' + (H - NB_PADB + 16) + ')');
        svg.appendChild(lab);
      }
    });

    body.appendChild(el('div', { class: 'dash-svg-wrap' }, [svg]));
    body.appendChild(el('div', { class: 'dash-axis-note', text: dimensionLabel(cfg.dimension) + (m.unit ? ', ' + m.unit : '') }));
  }

  function renderLine(groups, m, cfg, body) {
    if (!groups.length) { body.appendChild(emptyBox('Нет данных для этого отбора.')); return; }
    var W = 420, H = 232, padL = 42, padR = 12, padT = 14, padB = 30;
    var innerW = W - padL - padR, innerH = H - padT - padB;
    var values = groups.map(function (g) { return g.value === null ? 0 : g.value; });
    var minV = Math.min.apply(null, values.concat([0]));
    var maxV = Math.max.apply(null, values.concat([0]));
    var ticks = niceTicks(minV, maxV, 5);
    var lo = ticks[0], hi = ticks[ticks.length - 1], span = hi - lo || 1;
    function y(v) { return padT + innerH - ((v - lo) / span) * innerH; }
    function x(i) { return groups.length === 1 ? padL + innerW / 2 : padL + (innerW / (groups.length - 1)) * i; }

    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': cfg.title, class: 'dash-svg' });
    ticks.forEach(function (t) {
      svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), class: 'dash-grid' }));
      var tx = svgEl('text', { x: padL - 8, y: y(t) + 4, class: 'dash-tick', 'text-anchor': 'end' });
      tx.textContent = (m.agg === 'share' || m.share)
        ? fmtShare(t, 0)
        : fmtNum(t, (m.agg === 'count' || m.agg === 'count_distinct') ? 0 : (Math.abs(hi - lo) < 10 ? 1 : 0));
      svg.appendChild(tx);
    });
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), class: 'dash-zero-line' }));

    var d = '';
    groups.forEach(function (g, i) {
      var v = g.value === null ? 0 : g.value;
      d += (i ? ' L' : 'M') + x(i) + ' ' + y(v);
    });
    svg.appendChild(svgEl('path', { d: d, class: 'dash-line', stroke: colorFor(cfg), fill: 'none' }));

    var labels = showsLabels(cfg);
    var step = Math.ceil(groups.length / 12);
    var labelAt = {};
    if (groups.length <= 6) {
      groups.forEach(function (g, i) { labelAt[i] = 1; });
    } else {
      var maxI = 0, minI = 0;
      groups.forEach(function (g, i) {
        var v = g.value === null ? -Infinity : g.value;
        if (v > (groups[maxI].value === null ? -Infinity : groups[maxI].value)) maxI = i;
        if (v < (groups[minI].value === null ? Infinity : groups[minI].value)) minI = i;
      });
      labelAt[0] = 1; labelAt[groups.length - 1] = 1; labelAt[maxI] = 1; labelAt[minI] = 1;
    }
    groups.forEach(function (g, i) {
      var v = g.value === null ? 0 : g.value;
      var dot = svgEl('circle', { cx: x(i), cy: y(v), r: 4, fill: colorFor(cfg), class: 'dash-dot' });
      dot.setAttribute('tabindex', '0');
      dot.setAttribute('role', 'button');
      dot.setAttribute('aria-label', g.key + ', ' + valueText(g.value, m, cfg));
      var tip = tipText(g, m, cfg);
      dot.addEventListener('mouseenter', function (e) { showTip(tip, e.clientX, e.clientY); });
      dot.addEventListener('mouseleave', hideTip);
      dot.addEventListener('focus', function () { var r = dot.getBoundingClientRect(); showTip(tip, r.left + r.width / 2, r.top); });
      dot.addEventListener('blur', hideTip);
      svg.appendChild(dot);
      if (labels && labelAt[i]) {
        var lv = svgEl('text', { x: x(i), y: y(v) - 10, class: 'dash-val', 'text-anchor': 'middle' });
        lv.textContent = valueText(g.value, m, cfg);
        svg.appendChild(lv);
      }
      if (i % step === 0 || i === groups.length - 1) {
        var lab = svgEl('text', { x: x(i), y: H - padB + 18, class: 'dash-cat', 'text-anchor': 'middle' });
        lab.textContent = g.key;
        svg.appendChild(lab);
      }
    });

    body.appendChild(el('div', { class: 'dash-svg-wrap' }, [svg]));
    body.appendChild(el('div', { class: 'dash-axis-note', text: dimensionLabel(cfg.dimension) + (m.unit ? ', ' + m.unit : '') }));
  }

  function renderTable(groups, rest, m, cfg, body) {
    var all = groups.slice();
    if (rest) all.push(rest);
    if (!all.length) { body.appendChild(emptyBox('Нет данных для этого отбора.')); return; }
    var total = all.length;
    if (all.length > TABLE_LIMIT) all = all.slice(0, TABLE_LIMIT);
    var table = el('table', { class: 'dash-table' });
    var head = el('tr');
    head.appendChild(el('th', { text: dimensionLabel(cfg.dimension), scope: 'col' }));
    head.appendChild(el('th', { text: m.label, scope: 'col', class: 'num' }));
    head.appendChild(el('th', { text: 'Строк', scope: 'col', class: 'num' }));
    table.appendChild(el('thead', {}, [head]));
    var tbody = el('tbody');
    all.forEach(function (g) {
      var tr = el('tr', { tabindex: '0' });
      tr.appendChild(el('td', { text: g.key }));
      tr.appendChild(el('td', { class: 'num', text: valueText(g.value, m, cfg) }));
      tr.appendChild(el('td', { class: 'num', text: String(g.den != null ? g.den : g.n) }));
      if (g.rows.length && !g.isRest) {
        tr.addEventListener('click', function () { toggleSelection(cfg.dimension, g.raw); });
        tr.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSelection(cfg.dimension, g.raw); }
        });
      } else {
        tr.removeAttribute('tabindex');
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    body.appendChild(el('div', { class: 'dash-table-wrap' }, [table]));
    if (total > all.length) {
      body.appendChild(el('p', {
        class: 'dash-note',
        text: 'Показаны первые ' + all.length + ' из ' + total + ' строк. Сузьте отбор или задайте Top N в настройках графика.'
      }));
    }
  }

  /* ────────────────────────────── карточки графиков ──────────────────────── */

  function effectiveChart(cfg) {
    var s = null;
    (SPEC.charts || []).forEach(function (c) { if (c.id === cfg.id) s = c; });
    s = s || {};
    var ov = cfg.overrides || {};
    return {
      id: cfg.id,
      title: cfg.title,
      dimension: cfg.dimension,
      measure: cfg.measure,
      type: cfg.type,
      sort: (ov.sort != null ? ov.sort : (s.sort == null ? null : s.sort)),
      topN: (ov.topN != null ? ov.topN : (s.topN == null ? null : s.topN)),
      rest: (s.rest == null ? null : s.rest),
      agg: s.agg || null,
      note: s.note || '',
      overrides: ov
    };
  }

  function chartBody(cfgIn, rows) {
    var cfg = effectiveChart(cfgIn);
    var body = el('div', { class: 'dash-chart-body' });
    var built = buildGroups(rows, cfg);
    var m = built.m;
    var type = cfg.type;
    if (!chartTypeIsCompatible(type, cfg.dimension, cfg.topN)) type = compatibleTypes(cfg.dimension)[0];
    if (type === 'hbar') renderHBar(built.groups, built.rest, m, cfg, body);
    else if (type === 'vbar') renderVBar(built.groups, built.rest, m, cfg, body);
    else if (type === 'line') renderLine(built.groups, m, cfg, body);
    else renderTable(built.groups, built.rest, m, cfg, body);
    return body;
  }

  function renderCharts(rows, container) {
    container.textContent = '';
    var visibleCount = 0;
    CONFIG.charts.forEach(function (cfg) {
      if (!cfg.visible) return;
      var eff = effectiveChart(cfg);
      var note = eff.note || '';
      var card = el('section', { class: 'dash-card', 'data-chart': cfg.id });
      var head = el('div', { class: 'dash-card-head' }, [
        el('h2', { text: cfg.title }),
        el('button', {
          class: 'dash-icon-btn sm', type: 'button', title: 'Настройки графика «' + cfg.title + '»',
          'aria-label': 'Настройки графика «' + cfg.title + '»',
          onclick: function () { openPanel('charts', cfg.id); }
        })
      ]);
      head.lastChild.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>';
      card.appendChild(head);
      var body = chartBody(cfg, rows);
      card.appendChild(body);
      if (note) card.appendChild(el('p', { class: 'dash-note', text: note }));
      container.appendChild(card);
      visibleCount++;
    });

    container.setAttribute('data-count', String(visibleCount));

    if (!visibleCount) {
      container.appendChild(el('div', { class: 'dash-allhidden' }, [
        el('p', { text: 'Все графики скрыты.' }),
        el('button', {
          class: 'dash-btn', type: 'button', text: 'Открыть настройки графиков',
          onclick: function () { openPanel('charts'); }
        })
      ]));
    }
  }

  function selectionText() {
    var bits = [];
    (SPEC.filters || []).forEach(function (f) {
      var v = STATE.filters[f.id];
      if (v === undefined || v === null || v === ALL) return;
      var label = f.valueLabels && f.valueLabels[v] ? f.valueLabels[v] : v;
      bits.push(f.label + ': ' + label);
    });
    if (STATE.selection) bits.push(dimensionLabel(STATE.selection.dimension) + ': ' + STATE.selection.value);
    return bits;
  }

  function renderSelection(container, rows) {
    container.textContent = '';
    container.appendChild(el('span', { class: 'dash-sel-base', text: 'Строк в отборе: ' + rows.length + ' из ' + ROWS.length }));
    selectionText().forEach(function (t) {
      container.appendChild(el('span', { class: 'dash-chip', text: t }));
    });
    if (selectionText().length) {
      container.appendChild(el('button', {
        class: 'dash-chip dash-chip-clear', type: 'button', text: 'Сбросить',
        onclick: function () { resetFilters(); }
      }));
    }
  }

  function renderFilters(container) {
    container.textContent = '';
    (SPEC.filters || []).forEach(function (f) {
      var id = 'f-' + f.id;
      var values = uniqueSorted(ROWS.map(function (r) { return cell(r, f.column); }));
      var select = el('select', { id: id, 'data-filter': f.id });
      select.appendChild(el('option', { value: ALL, text: 'Все' }));
      values.forEach(function (v) {
        var label = f.valueLabels && f.valueLabels[v] ? f.valueLabels[v] : String(v);
        select.appendChild(el('option', { value: String(v), text: label }));
      });
      var cur = STATE.filters[f.id];
      select.value = (cur === undefined || cur === null) ? ALL : String(cur);
      select.addEventListener('change', function () {
        STATE.filters[f.id] = select.value;
        STATE.selection = null;
        renderAll();
      });
      container.appendChild(el('label', { class: 'dash-filter' }, [
        el('span', { text: f.label }), select
      ]));
    });
  }

  /* ─────────────────────────────── рендер всего ─────────────────────────── */

  var refs = {};

  function renderAll() {
    document.documentElement.style.setProperty('--chart-color', CONFIG.global.accent);
    document.body.classList.toggle('theme-dark', CONFIG.global.theme === 'dark');
    var t = document.getElementById('dash-title');
    if (t) t.textContent = CONFIG.global.title || SPEC.title || 'Дашборд';
    document.title = CONFIG.global.title || SPEC.title || 'Дашборд';
    if (SPEC.question && refs.question) refs.question.textContent = SPEC.question;

    var rows = filteredRows();
    // Селекты держим в согласии со STATE: иначе после «Сбросить» или
    // клика по категории в поле остаётся старое значение.
    if (refs.filters) {
      refs.filters.querySelectorAll('select[data-filter]').forEach(function (sel) {
        var id = sel.getAttribute('data-filter');
        var v = STATE.filters[id];
        sel.value = (v === undefined || v === null) ? ALL : String(v);
      });
    }
    renderKpis(rows, refs.kpis);
    renderCharts(rows, refs.charts);
    renderSelection(refs.selection, rows);
    var banner = refs.banner;
    banner.textContent = '';
    if (!rows.length) {
      banner.appendChild(el('div', { class: 'dash-empty' }, [
        el('p', { text: 'В выбранном отборе нет строк. Измените фильтры или сбросьте отбор.' }),
        el('button', { class: 'dash-btn', type: 'button', text: 'Сбросить отбор', onclick: function () { resetFilters(); } })
      ]));
    }
    if (REMEMBER.panelOpen) syncPanel();
  }

  function resetFilters() {
    (SPEC.filters || []).forEach(function (f) {
      var values = uniqueSorted(ROWS.map(function (r) { return cell(r, f.column); }));
      STATE.filters[f.id] = f.default === 'last' && values.length ? String(values[values.length - 1]) : ALL;
    });
    STATE.selection = null;
    renderAll();
  }

  function toggleSelection(dimension, value) {
    var same = STATE.selection && STATE.selection.dimension === dimension && String(STATE.selection.value) === String(value);
    STATE.selection = same ? null : { dimension: dimension, value: value };
    renderAll();
  }

  /* ───────────────────────────── панель настроек ─────────────────────────── */

  var REMEMBER = { panelOpen: false, tab: 'general', focusChart: null };

  function openPanel(tab, chartId) {
    // Снимок настроек: «Отмена» возвращает то, что было при открытии панели.
    REMEMBER.snapshot = JSON.parse(JSON.stringify(CONFIG));
    REMEMBER.panelOpen = true;
    REMEMBER.tab = tab || 'general';
    REMEMBER.focusChart = chartId || null;
    panelEl.classList.add('open');
    panelEl.setAttribute('aria-hidden', 'false');
    syncPanel();
    var first = panelEl.querySelector('.dash-tab-btn.active') || panelEl;
    if (first && first.focus) first.focus();
  }

  function closePanel() {
    REMEMBER.panelOpen = false;
    panelEl.classList.remove('open');
    panelEl.setAttribute('aria-hidden', 'true');
    if (refs.settingsBtn) refs.settingsBtn.focus();
  }

  function tabButton(id, label) {
    var b = el('button', {
      class: 'dash-tab-btn' + (REMEMBER.tab === id ? ' active' : ''), type: 'button', 'data-tab': id, text: label,
      onclick: function () { REMEMBER.tab = id; syncPanel(); }
    });
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', REMEMBER.tab === id ? 'true' : 'false');
    return b;
  }

  function field(labelText, control) {
    var lab = el('label', { class: 'dash-field' });
    lab.appendChild(el('span', { text: labelText }));
    lab.appendChild(control);
    return lab;
  }

  function syncPanel() {
    panelEl.querySelectorAll('.dash-tab-btn').forEach(function (b) {
      var on = b.getAttribute('data-tab') === REMEMBER.tab;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    var general = panelEl.querySelector('#dash-tab-general');
    var chartsTab = panelEl.querySelector('#dash-tab-charts');
    general.hidden = REMEMBER.tab !== 'general';
    chartsTab.hidden = REMEMBER.tab !== 'charts';
    if (REMEMBER.tab === 'general') syncGeneral();
    else syncChartsTab();
  }

  function syncGeneral() {
    var box = panelEl.querySelector('#dash-tab-general');
    box.textContent = '';
    var title = el('input', { type: 'text', value: CONFIG.global.title, 'data-g': 'title' });
    title.addEventListener('input', function () {
      CONFIG.global.title = title.value.slice(0, 200);
      var t = document.getElementById('dash-title');
      if (t) t.textContent = CONFIG.global.title;
      document.title = CONFIG.global.title;
    });
    box.appendChild(field('Заголовок страницы', title));

    var theme = el('select', { 'data-g': 'theme' });
    theme.appendChild(el('option', { value: 'light', text: 'Светлая' }));
    theme.appendChild(el('option', { value: 'dark', text: 'Тёмная' }));
    theme.value = CONFIG.global.theme;
    theme.addEventListener('change', function () { CONFIG.global.theme = theme.value; renderAll(); });
    box.appendChild(field('Тема', theme));

    var accent = el('input', { type: 'color', value: CONFIG.global.accent, 'data-g': 'accent' });
    accent.addEventListener('input', function () { CONFIG.global.accent = accent.value; renderAll(); });
    box.appendChild(field('Общий цвет графиков', accent));

    var dec = el('input', { type: 'number', min: '0', max: '4', step: '1', value: String(CONFIG.global.decimals), 'data-g': 'decimals' });
    dec.addEventListener('input', function () {
      var n = Number(dec.value);
      if (!isFinite(n)) return;
      CONFIG.global.decimals = Math.max(0, Math.min(4, Math.round(n)));
      renderAll();
    });
    box.appendChild(field('Знаков после запятой', dec));

    var labels = el('input', { type: 'checkbox' });
    labels.checked = !!CONFIG.global.showLabels;
    labels.addEventListener('change', function () { CONFIG.global.showLabels = labels.checked; renderAll(); });
    var labWrap = el('label', { class: 'dash-toggle' }, [labels, el('span', { text: 'Подписи значений на графиках' })]);
    box.appendChild(labWrap);

    var details = el('details', { class: 'dash-details' });
    details.appendChild(el('summary', { text: 'Конфигурация (JSON)' }));
    var area = el('textarea', { rows: '8', spellcheck: 'false', class: 'dash-json' });
    area.value = JSON.stringify({ version: 5, global: CONFIG.global, charts: CONFIG.charts }, null, 2);
    details.appendChild(area);
    var row = el('div', { class: 'dash-row' });
    row.appendChild(el('button', {
      class: 'dash-btn', type: 'button', text: 'Экспорт в поле',
      onclick: function () { area.value = JSON.stringify({ version: 5, global: CONFIG.global, charts: CONFIG.charts }, null, 2); }
    }));
    row.appendChild(el('button', {
      class: 'dash-btn', type: 'button', text: 'Импорт из поля',
      onclick: function () {
        var parsed;
        try { parsed = JSON.parse(area.value); } catch (e) { setStatus('Невалидный JSON: ' + e.message); return; }
        var err = validateConfig(parsed);
        if (err) { setStatus('Импорт отклонён: ' + err); return; }
        CONFIG = normaliseConfig(parsed);
        renderAll();
        syncPanel();
        setStatus('Конфигурация импортирована.');
      }
    }));
    details.appendChild(row);
    details.appendChild(el('p', { class: 'dash-status', id: 'dash-status', text: '' }));
    box.appendChild(details);
  }

  function setStatus(text) {
    var n = panelEl.querySelector('#dash-status');
    if (n) n.textContent = text;
  }

  function syncChartsTab() {
    var box = panelEl.querySelector('#dash-tab-charts');
    box.textContent = '';
    CONFIG.charts.forEach(function (cfg) {
      var card = el('div', { class: 'dash-cfg-card', 'data-cfg': cfg.id });
      if (REMEMBER.focusChart === cfg.id) card.classList.add('focus');

      var head = el('div', { class: 'dash-cfg-head' }, [
        el('strong', { text: cfg.title }),
        el('span', { class: 'dash-badge' + (cfg.visible ? ' hidden-badge' : ''), text: cfg.visible ? 'виден' : 'скрыт' })
      ]);
      card.appendChild(head);

      var vis = el('input', { type: 'checkbox' });
      vis.checked = !!cfg.visible;
      vis.addEventListener('change', function () {
        cfg.visible = vis.checked;
        renderAll();
        syncPanel();
      });
      card.appendChild(el('label', { class: 'dash-toggle' }, [vis, el('span', { text: 'Показывать график' })]));

      var t = el('input', { type: 'text', value: cfg.title });
      t.addEventListener('input', function () { cfg.title = t.value.slice(0, 200); renderAll(); });
      card.appendChild(field('Заголовок', t));

      var dim = el('select');
      Object.keys(DIMS).forEach(function (d) {
        if (IDX[d] === undefined) return;
        dim.appendChild(el('option', { value: d, text: DIMS[d].label || d }));
      });
      dim.value = cfg.dimension;
      dim.addEventListener('change', function () {
        cfg.dimension = dim.value;
        if (!chartTypeIsCompatible(cfg.type, cfg.dimension, cfg.overrides.topN)) {
          cfg.type = compatibleTypes(cfg.dimension)[0];
        }
        renderAll();
        syncPanel();
      });
      card.appendChild(field('Измерение (группировка)', dim));

      var mea = el('select');
      Object.keys(MEASURES).forEach(function (k) {
        mea.appendChild(el('option', { value: k, text: MEASURES[k].label || k }));
      });
      mea.value = cfg.measure;
      mea.addEventListener('change', function () { cfg.measure = mea.value; renderAll(); });
      card.appendChild(field('Показатель', mea));

      var typ = el('select');
      compatibleTypes(cfg.dimension).forEach(function (tp) {
        typ.appendChild(el('option', { value: tp, text: { hbar: 'Горизонтальные столбцы', vbar: 'Вертикальные столбцы', line: 'Линия', table: 'Таблица' }[tp] }));
      });
      typ.value = cfg.type;
      typ.addEventListener('change', function () { cfg.type = typ.value; renderAll(); });
      card.appendChild(field('Тип', typ));

      var own = el('input', { type: 'checkbox' });
      own.checked = !!cfg.overrides.color;
      var col = el('input', { type: 'color', value: cfg.overrides.color || CONFIG.global.accent });
      col.disabled = !own.checked;
      own.addEventListener('change', function () {
        cfg.overrides.color = own.checked ? (cfg.overrides.color || CONFIG.global.accent) : null;
        renderAll();
        syncPanel();
      });
      col.addEventListener('input', function () { cfg.overrides.color = col.value; renderAll(); });
      var colorRow = el('div', { class: 'dash-row' }, [
        el('label', { class: 'dash-toggle' }, [own, el('span', { text: 'Свой цвет' })]), col
      ]);
      card.appendChild(colorRow);

      var adv = el('details', { class: 'dash-details' });
      adv.appendChild(el('summary', { text: 'Дополнительно' }));

      var sort = el('select');
      sort.appendChild(el('option', { value: 'desc', text: 'По убыванию' }));
      sort.appendChild(el('option', { value: 'asc', text: 'По возрастанию' }));
      sort.value = cfg.overrides.sort || 'desc';
      sort.addEventListener('change', function () { cfg.overrides.sort = sort.value; renderAll(); });
      adv.appendChild(field('Сортировка', sort));

      var topn = el('input', { type: 'number', min: '1', max: '500', step: '1', value: cfg.overrides.topN == null ? '' : String(cfg.overrides.topN), placeholder: 'все' });
      topn.addEventListener('input', function () {
        var v = topn.value.trim();
        cfg.overrides.topN = v === '' ? null : Math.max(1, Math.min(500, Math.round(Number(v))));
        if (!chartTypeIsCompatible(cfg.type, cfg.dimension, cfg.overrides.topN)) cfg.type = compatibleTypes(cfg.dimension)[0];
        renderAll();
      });
      adv.appendChild(field('Top N', topn));

      var dec2 = el('input', { type: 'number', min: '0', max: '4', step: '1', value: cfg.overrides.decimals == null ? '' : String(cfg.overrides.decimals), placeholder: 'наследуется' });
      dec2.addEventListener('input', function () {
        var v = dec2.value.trim();
        cfg.overrides.decimals = v === '' ? null : Math.max(0, Math.min(4, Math.round(Number(v))));
        renderAll();
      });
      adv.appendChild(field('Точность (наследует общую)', dec2));

      var lab2 = el('input', { type: 'checkbox' });
      lab2.checked = cfg.overrides.showLabels === true;
      lab2.addEventListener('change', function () {
        cfg.overrides.showLabels = lab2.checked ? true : null;
        renderAll();
      });
      adv.appendChild(el('label', { class: 'dash-toggle' }, [lab2, el('span', { text: 'Подписи значений (переопределить)' })]));

      adv.appendChild(el('button', {
        class: 'dash-btn', type: 'button', text: 'Сбросить переопределения',
        onclick: function () {
          cfg.overrides = { color: null, decimals: null, showLabels: null, sort: null, topN: null };
          renderAll();
          syncPanel();
        }
      }));
      card.appendChild(adv);
      box.appendChild(card);
    });
  }

  /* ───────────────────────────── сохранение HTML ─────────────────────────── */

  function saveHtml() {
    var store = document.getElementById('config-store');
    if (store) {
      var stateToSave = { filters: STATE.filters, selection: STATE.selection };
      store.textContent = 'window.__CONFIG__ = ' + JSON.stringify(CONFIG) + ';\n' +
        'window.__STATE__ = ' + JSON.stringify(stateToSave) + ';';
    }
    panelEl.classList.remove('open');
    panelEl.setAttribute('aria-hidden', 'true');
    hideTip();
    var html = '<!doctype html>\n' + document.documentElement.outerHTML;
    if (REMEMBER.panelOpen) {
      panelEl.classList.add('open');
      panelEl.setAttribute('aria-hidden', 'false');
    }
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var name = (CONFIG.global.title || 'dashboard').replace(/[^\wа-яА-ЯёЁ\d-]+/g, '_').slice(0, 60) || 'dashboard';
    var a = document.createElement('a');
    a.href = url;
    a.download = name + '.html';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  /* ───────────────────────────────── запуск ──────────────────────────────── */

  function buildShell() {
    root.textContent = '';

    var saveBtn = el('button', {
      class: 'dash-icon-btn', type: 'button', title: 'Сохранить HTML', 'aria-label': 'Сохранить HTML',
      onclick: saveHtml
    });
    saveBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" d="M5 3h11l3 3v15H5z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M8 3v6h8V3M8 21v-7h8v7"/></svg>';
    var setBtn = el('button', {
      class: 'dash-icon-btn', type: 'button', title: 'Настройки', 'aria-label': 'Настройки',
      onclick: function () { openPanel('general'); }
    });
    setBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>';

    var top = el('header', { class: 'dash-top' }, [
      el('div', { class: 'dash-top-text' }, [
        el('h1', { id: 'dash-title', text: CONFIG.global.title }),
        el('p', { class: 'dash-question', id: 'dash-question', text: SPEC.question || '' })
      ]),
      el('div', { class: 'dash-actions' }, [saveBtn, setBtn])
    ]);
    root.appendChild(top);

    var filters = el('div', { class: 'dash-filters', id: 'dash-filters' });
    // Без фильтров не оставляем пустую рамку на странице.
    if (!(SPEC.filters || []).length) filters.hidden = true;
    root.appendChild(filters);
    var selection = el('div', { class: 'dash-selection', id: 'dash-selection' });
    root.appendChild(selection);
    var banner = el('div', { id: 'dash-banner' });
    root.appendChild(banner);
    var kpis = el('div', { class: 'dash-kpis', id: 'dash-kpis' });
    root.appendChild(kpis);
    var charts = el('div', { class: 'dash-grid', id: 'dash-charts' });
    root.appendChild(charts);

    if (SPEC.source || SPEC.note) {
      var meta = el('p', { class: 'dash-meta' });
      if (SPEC.source) meta.appendChild(el('span', { text: 'Источник: ' + SPEC.source + '. ' }));
      if (SPEC.note) meta.appendChild(el('span', { text: SPEC.note }));
      root.appendChild(meta);
    }

    var skill = el('details', { class: 'dash-skill' });
    skill.appendChild(el('summary', { text: 'Skill.MD — полный текст версии' }));
    var pre = el('pre', {});
    pre.textContent = SPEC.skill || 'Текст Skill.MD не встроен в эту страницу.';
    skill.appendChild(pre);
    if (SPEC.skill) {
      skill.appendChild(el('button', {
        class: 'dash-btn', type: 'button', text: 'Скачать Skill.MD',
        onclick: function () {
          var blob = new Blob([SPEC.skill], { type: 'text/markdown;charset=utf-8' });
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url; a.download = 'SKILL.md';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
        }
      }));
    }
    root.appendChild(skill);

    refs = {
      saveBtn: saveBtn, settingsBtn: setBtn, filters: filters, selection: selection,
      banner: banner, kpis: kpis, charts: charts, question: document.getElementById('dash-question')
    };

    panelEl.textContent = '';
    var head = el('div', { class: 'dash-panel-head' }, [
      el('h2', { text: 'Настройки' }),
      el('button', {
        class: 'dash-icon-btn sm', type: 'button', title: 'Закрыть', 'aria-label': 'Закрыть настройки',
        onclick: closePanel
      })
    ]);
    head.lastChild.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" d="M6 6l12 12M18 6L6 18"/></svg>';
    panelEl.appendChild(head);
    panelEl.appendChild(el('div', { class: 'dash-tabs', role: 'tablist' }, [tabButton('general', 'Общие'), tabButton('charts', 'Графики')]));
    var body = el('div', { class: 'dash-panel-body' });
    body.appendChild(el('div', { id: 'dash-tab-general', role: 'tabpanel' }));
    body.appendChild(el('div', { id: 'dash-tab-charts', role: 'tabpanel', hidden: 'hidden' }));
    panelEl.appendChild(body);
    panelEl.appendChild(el('div', { class: 'dash-panel-foot' }, [
      el('button', {
        class: 'dash-btn', type: 'button', text: 'Отмена',
        onclick: function () {
          if (REMEMBER.snapshot) CONFIG = normaliseConfig(REMEMBER.snapshot);
          renderAll();
          closePanel();
        }
      }),
      el('button', {
        class: 'dash-btn', type: 'button', text: 'Сбросить оформление',
        onclick: function () {
          // Видимость графиков не трогаем: §4 — сброс оформления не меняет
          // видимость и не удаляет настройки.
          var visibility = {};
          CONFIG.charts.forEach(function (c) { visibility[c.id] = c.visible; });
          var fresh = defaultConfig();
          fresh.charts.forEach(function (c) { c.visible = visibility[c.id] !== false; });
          CONFIG = fresh;
          renderAll();
          syncPanel();
        }
      })
    ]));
  }

  function init() {
    buildShell();
    renderFilters(refs.filters);
    renderAll();
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panelEl.classList.contains('open')) closePanel();
    });
  }

  /* Публичный API для автопроверки (/opt/viz/kit/verify_page.py). */
  window.DASH = {
    spec: SPEC,
    data: DATA,
    get config() { return CONFIG; },
    get state() { return STATE; },
    setFilter: function (id, value) { STATE.filters[id] = value; STATE.selection = null; renderAll(); },
    select: function (dimension, value) { toggleSelection(dimension, value); },
    reset: resetFilters,
    applyConfig: function (raw) {
      var err = validateConfig(raw);
      if (err) return err;
      CONFIG = normaliseConfig(raw);
      renderAll();
      return '';
    },
    kpiValues: function () {
      return Array.prototype.map.call(document.querySelectorAll('.dash-kpi'), function (n) {
        return {
          label: (n.querySelector('.dash-kpi-label') || {}).textContent,
          value: (n.querySelector('.dash-kpi-value') || {}).textContent
        };
      });
    },
    chartValues: function (id) {
      var card = document.querySelector('[data-chart="' + id + '"]');
      if (!card) return null;
      return Array.prototype.map.call(card.querySelectorAll('.dash-hrow'), function (row) {
        return {
          label: (row.querySelector('.dash-hlabel') || {}).textContent,
          value: (row.querySelector('.dash-hvalue') || {}).textContent
        };
      });
    },
    chartCount: function () { return document.querySelectorAll('[data-chart]').length; },
    rowsInSelection: function () { return filteredRows().length; },
    selectionText: function () { return selectionText(); }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
