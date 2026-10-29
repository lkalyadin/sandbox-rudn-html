#!/usr/bin/env python3
"""Проверка для разработчика kit: панель, «Отмена», сохранение и повторное открытие.

Что проверяет (то, чего нет в /opt/viz/kit/verify_page.py):
  1. шестерёнка открывает панель настроек;
  2. смена темы применяется сразу;
  3. «Отмена» возвращает настройки к моменту открытия панели;
  4. дискетка собирает автономный HTML: в нём есть CONFIG, текст Skill.MD и
     разметка, а сохранённая тема сохраняется;
  5. сохранённый файл открывается без ошибок и проходит verify_page.

Запуск (обычно после правок engine.js/template.html):

    python3 /opt/viz/kit/dev/roundtrip_probe.py output/dashboard.html

Рядом появятся `<имя>.probe.html` и `<имя>.saved.html` — их можно удалить.
Код выхода 0 — всё сошлось.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import subprocess
import sys

VIZ_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VIZ_DIR))

from check_page import run_browser  # noqa: E402

JS = r"""
(function(){
  function emit(id, text){ var pre=document.createElement("pre"); pre.id=id; pre.textContent=text; document.body.appendChild(pre); }
  function done(res){ emit("probe-result", btoa(unescape(encodeURIComponent(JSON.stringify(res))))); }
  window.addEventListener("load", function(){ setTimeout(function(){
    var res={};
    try {
      var panel=document.getElementById("dash-panel");
      var actions=document.querySelectorAll(".dash-actions .dash-icon-btn");
      actions[actions.length-1].click();
      res.opened=panel.classList.contains("open");
      var sel=panel.querySelector('select[data-g="theme"]');
      sel.value="dark"; sel.dispatchEvent(new Event("change"));
      res.darkBefore=document.body.classList.contains("theme-dark");
      var cancel=panel.querySelectorAll(".dash-panel-foot .dash-btn")[0];
      cancel.click();
      res.darkAfterCancel=document.body.classList.contains("theme-dark");
      res.panelClosed=!panel.classList.contains("open");
      var cfg=JSON.parse(JSON.stringify(window.DASH.config));
      cfg.global.theme="dark";
      cfg.charts[1].visible=false;
      window.DASH.applyConfig(cfg);
      var orig=URL.createObjectURL;
      URL.createObjectURL=function(blob){
        res.blobSize=blob.size;
        blob.text().then(function(t){
          res.savedHasConfig=t.indexOf("window.__CONFIG__")>=0;
          res.savedHasSkill=t.indexOf("Skill.MD")>=0;
          res.savedHasMarkup=t.indexOf("dash-hbar")>=0;
          res.savedHasDark=t.indexOf('"theme":"dark"')>=0;
          emit("probe-saved", btoa(unescape(encodeURIComponent(t))));
          URL.createObjectURL=orig;
          done(res);
        });
        return "blob:probe";
      };
      actions[0].click();
    } catch(e){ res.error=String(e); done(res); }
  }, 50); });
})();
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("укажите путь к собранной странице", file=sys.stderr)
        return 2
    page = pathlib.Path(argv[0]).resolve()
    if not page.is_file():
        print(f"файл не найден: {page}", file=sys.stderr)
        return 2

    probe = page.with_suffix(".probe.html")
    probe.write_text(page.read_text(encoding="utf-8")
                     .replace("</body>", "<script>" + JS + "</script></body>"))

    err, dom, fatal = run_browser("file://" + str(probe))
    m = re.search(r'<pre id="probe-result">(.*?)</pre>', dom or "", re.S)
    if not m:
        print(f"страница не отдала результат; fatal={fatal}", file=sys.stderr)
        print("\n".join((err or "").splitlines()[-6:]), file=sys.stderr)
        return 1

    payload = json.loads(base64.b64decode(re.sub(r"\s+", "", m.group(1))))
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    ok = (payload.get("opened") and payload.get("darkBefore")
          and not payload.get("darkAfterCancel") and payload.get("panelClosed")
          and payload.get("savedHasConfig") and payload.get("savedHasSkill")
          and payload.get("savedHasMarkup") and payload.get("savedHasDark"))

    saved = re.search(r'<pre id="probe-saved">(.*?)</pre>', dom or "", re.S)
    if saved:
        text = base64.b64decode(re.sub(r"\s+", "", saved.group(1))).decode("utf-8")
        target = page.with_suffix(".saved.html")
        target.write_text(text, encoding="utf-8")
        print(f"сохранённая копия: {target} ({len(text) // 1024} КБ)")
        for script in (VIZ_DIR / "check_page.py", VIZ_DIR / "kit" / "verify_page.py"):
            proc = subprocess.run([sys.executable, str(script), str(target)],
                                  capture_output=True, text=True)
            tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1:]
            print(f"  {script.name}: exit={proc.returncode} | {' '.join(tail)}")
            ok = ok and proc.returncode == 0
    else:
        ok = False

    probe.unlink(missing_ok=True)
    print("ИТОГ:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
