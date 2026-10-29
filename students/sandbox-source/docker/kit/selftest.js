/* Автопроверка интерактивной части страницы (/opt/viz/kit/verify_page.py).
 *
 * Запускается внутри страницы после отрисовки. Пишет результат в
 * отдельный <pre> в base64, чтобы не спорить с экранированием HTML.
 * Ничего не оставляет после себя: конфигурация и отбор восстанавливаются.
 */
(function () {
  'use strict';

  var results = [];

  function check(name, fn) {
    try {
      var detail = fn();
      results.push({ name: name, ok: detail !== false, detail: detail === false ? 'не выполнено' : (detail || '') });
    } catch (err) {
      results.push({ name: name, ok: false, detail: 'исключение: ' + (err && err.message ? err.message : err) });
    }
  }

  function emit(errorText) {
    var payload = { ok: results.every(function (r) { return r.ok; }), checks: results, error: errorText || '' };
    var json = JSON.stringify(payload);
    var pre = document.createElement('pre');
    pre.id = 'dash-selftest-result';
    try { pre.textContent = btoa(unescape(encodeURIComponent(json))); }
    catch (e) { pre.textContent = btoa(JSON.stringify({ ok: false, checks: [], error: 'encode: ' + e.message })); }
    document.body.appendChild(pre);
  }

  function run() {
    var D = window.DASH;
    if (!D) { emit('window.DASH отсутствует: страница собрана не через /opt/viz/kit или движок упал'); return; }

    var baseRows = D.rowsInSelection();
    var baseCharts = D.chartCount();
    var baseConfig = JSON.parse(JSON.stringify(D.config));

    check('движок инициализирован, KPI есть', function () {
      var kpis = D.kpiValues();
      if (kpis.length < 3) return 'KPI: ' + kpis.length + ' (нужно 3–4)';
      var silent = kpis.filter(function (k) { return !k.value || k.value === '—'; });
      if (silent.length === kpis.length) return 'все KPI пустые';
      return kpis.length + ' KPI, например «' + kpis[0].label + ': ' + kpis[0].value + '»';
    });

    check('видимые графики нарисованы', function () {
      if (!baseCharts) return 'ни одного видимого графика';
      var cards = document.querySelectorAll('[data-chart]');
      var rendered = 0;
      Array.prototype.forEach.call(cards, function (card) {
        if (card.querySelector('.dash-hrow, .dash-svg .dash-bar, .dash-dot, .dash-table tbody tr')) rendered++;
      });
      if (!rendered) return 'карточки есть, но внутри нет ни столбцов, ни линий, ни строк таблицы';
      return rendered + ' из ' + card_count() + ' карточек с содержимым';
    });

    function card_count() { return document.querySelectorAll('[data-chart]').length; }

    check('фильтр сужает выборку', function () {
      var filters = (D.spec.filters || []);
      for (var i = 0; i < filters.length; i++) {
        var f = filters[i];
        var idx = D.data.columns.indexOf(f.column);
        if (idx < 0) continue;
        var seen = {}, values = [];
        D.data.rows.forEach(function (r) { var v = r[idx]; if (v === null || v === undefined) return; var k = String(v); if (!(k in seen)) { seen[k] = 1; values.push(v); } });
        if (values.length < 2) continue;
        for (var j = 0; j < values.length; j++) {
          D.setFilter(f.id, String(values[j]));
          var n = D.rowsInSelection();
          if (n < baseRows) {
            D.reset();
            return 'фильтр «' + f.label + '» → ' + n + ' из ' + baseRows + ' строк';
          }
        }
        D.reset();
      }
      return false;
    });

    check('клик по категории работает как отбор', function () {
      var charts = D.spec.charts || [];
      for (var i = 0; i < charts.length; i++) {
        var c = charts[i];
        var idx = D.data.columns.indexOf(c.dimension);
        if (idx < 0) continue;
        var seen = {}, values = [];
        D.data.rows.forEach(function (r) { var v = r[idx]; if (v === null || v === undefined) return; var k = String(v); if (!(k in seen)) { seen[k] = 1; values.push(v); } });
        if (values.length < 2) continue;
        D.reset();
        D.select(c.dimension, values[0]);
        var narrowed = D.rowsInSelection();
        var chip = D.selectionText().length > 0;
        D.select(c.dimension, values[0]);   // повторный клик снимает отбор
        var restored = D.rowsInSelection();
        if (narrowed < baseRows && chip && restored === baseRows) {
          return 'отбор по «' + c.dimension + '»: ' + narrowed + ' строк, повторный клик вернул ' + restored;
        }
        D.reset();
        return 'отбор не сработал: строк ' + narrowed + ', плашка ' + chip + ', возврат ' + restored;
      }
      return false;
    });

    check('скрытие графика убирает карточку', function () {
      var cfg = JSON.parse(JSON.stringify(D.config));
      var target = cfg.charts[0];
      var wasVisible = target.visible;
      target.visible = !wasVisible;
      var err = D.applyConfig(cfg);
      if (err) return 'applyConfig вернул ошибку: ' + err;
      var expected = baseCharts + (wasVisible ? -1 : 1);
      var got = D.chartCount();
      D.applyConfig(baseConfig);
      if (got !== expected) return 'карточек ' + got + ', ожидалось ' + expected;
      return 'карточек ' + got + ', настройки вернулись';
    });

    check('невалидная конфигурация отклоняется', function () {
      var bad = { version: 5, global: { theme: 'light', accent: 'не-цвет', decimals: 1, showLabels: true }, charts: [] };
      var err = D.applyConfig(bad);
      var stillOk = D.chartCount() === baseCharts;
      if (!err) return 'импорт невалидного конфига был принят';
      if (!stillOk) return 'после отказа конфигурация всё-таки изменилась';
      return 'отклонено: ' + err;
    });

    check('тёмная тема применяется', function () {
      var cfg = JSON.parse(JSON.stringify(baseConfig));
      cfg.global.theme = 'dark';
      var err = D.applyConfig(cfg);
      if (err) return 'applyConfig вернул ошибку: ' + err;
      var dark = document.body.classList.contains('theme-dark');
      D.applyConfig(baseConfig);
      if (!dark) return 'класс theme-dark не появился';
      return 'тёмная тема включается и снимается';
    });

    check('поля фильтров согласованы с отбором', function () {
      var filters = D.spec.filters || [];
      if (!filters.length) return false;
      // Ставим заведомо другой отбор, затем сбрасываем и сверяем селекты.
      var first = filters[0];
      var sel = document.querySelector('select[data-filter="' + first.id + '"]');
      var values = Array.prototype.map.call(sel.options, function (o) { return o.value; });
      var other = values.filter(function (v) { return v !== sel.value; })[0];
      if (other !== undefined) {
        sel.value = other;
        sel.dispatchEvent(new Event('change'));
      }
      D.reset();
      var bad = [];
      filters.forEach(function (f) {
        var node = document.querySelector('select[data-filter="' + f.id + '"]');
        if (!node) return;
        var v = D.state.filters[f.id];
        var expect = (v === undefined || v === null) ? node.options[0].value : String(v);
        if (node.value !== expect) bad.push(f.id + ': поле ' + node.value + ', отбор ' + expect);
      });
      if (bad.length) return bad.join('; ');
      return filters.length + ' фильтров совпадают после сброса';
    });

    check('сброс отбора возвращает исходную выборку', function () {
      D.reset();
      var n = D.rowsInSelection();
      if (n !== baseRows) return 'строк ' + n + ', было ' + baseRows;
      return n + ' строк';
    });

    check('текст Skill.MD встроен', function () {
      var pre = document.querySelector('.dash-skill pre');
      if (!pre) return 'блока «Skill.MD» нет на странице';
      var len = (pre.textContent || '').length;
      if (!D.spec.skill) return false;
      if (len < 200) return 'текст слишком короткий: ' + len + ' символов';
      return len + ' символов';
    });

    check('внешних ресурсов нет', function () {
      var bad = [];
      document.querySelectorAll('script[src], link[href], img[src], iframe[src]').forEach(function (n) {
        var url = n.getAttribute('src') || n.getAttribute('href') || '';
        if (/^(https?:)?\/\//i.test(url)) bad.push(url);
      });
      if (bad.length) return 'внешние ресурсы: ' + bad.slice(0, 3).join(', ');
      return 'все ресурсы внутри файла';
    });

    D.applyConfig(baseConfig);
    D.reset();
    emit('');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(run, 0); });
  } else {
    setTimeout(run, 0);
  }
})();
