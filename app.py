import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import webview

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
PAGES_DIR = OUTPUT_DIR / "pages"
PRESENTATION_FILE = OUTPUT_DIR / "presentation.html"


@dataclass
class CrawlResult:
    url: str
    title: str
    local_file: Path


class Api:
    """JS API object. Keep only simple attributes to avoid pywebview recursion issues."""

    def _emit_js(self, script: str):
        if webview.windows:
            webview.windows[0].evaluate_js(script)

    def _emit_progress(self, value: int, text: str):
        self._emit_js(f"window.updateProgress({value}, {json.dumps(text)});")

    def _emit_status(self, text: str):
        self._emit_js(f"window.setStatus({json.dumps(text)});")

    def _emit_presentation_ready(self, path: str):
        self._emit_js(f"window.setPresentationPath({json.dumps(path)});")

    def build_from_url(self, start_url: str, max_pages=None):
        max_pages = self._normalize_limit(max_pages)
        thread = threading.Thread(target=self._run_pipeline, args=(start_url, max_pages), daemon=True)
        thread.start()
        return {"status": "started", "max_pages": max_pages}

    @staticmethod
    def _normalize_limit(raw_limit) -> Optional[int]:
        if raw_limit == "NO_LIMIT":
            return None
        if raw_limit in (None, "", 0, "0"):
            return 30
        try:
            value = int(raw_limit)
        except Exception:
            return 30
        return max(1, min(value, 200))

    def _run_pipeline(self, start_url: str, max_pages: Optional[int]):
        try:
            OUTPUT_DIR.mkdir(exist_ok=True)
            PAGES_DIR.mkdir(exist_ok=True)

            self._emit_progress(5, "Старт обработки")
            pages = self._crawl_site(start_url, max_pages)
            if not pages:
                self._emit_status("Не удалось собрать страницы. Проверьте ссылку/доступ.")
                return

            self._emit_progress(75, "Собран HTML, формируем презентацию")
            self._build_presentation(pages)
            self._emit_progress(100, "Презентация готова")
            self._emit_status(f"Готово: {len(pages)} страниц(ы).")
            self._emit_presentation_ready(PRESENTATION_FILE.resolve().as_uri())
        except Exception as exc:
            self._emit_status(f"Ошибка: {exc}")

    def _crawl_site(self, start_url: str, max_pages: Optional[int]) -> List[CrawlResult]:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 pywebview-crawler"})
        domain = urlparse(start_url).netloc

        to_visit = [start_url]
        visited = set()
        results: List[CrawlResult] = []

        while to_visit and (max_pages is None or len(results) < max_pages):
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)

            try:
                response = session.get(current, timeout=20)
                response.raise_for_status()
            except Exception:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else current

            idx = len(results) + 1
            local_file = PAGES_DIR / f"page_{idx}.html"
            local_file.write_text(response.text, encoding="utf-8", errors="ignore")
            results.append(CrawlResult(url=current, title=title, local_file=local_file))

            if max_pages is None:
                progress = min(70, 5 + len(results))
                self._emit_progress(progress, f"Собрано страниц: {len(results)} (без лимита)")
            else:
                progress = min(70, 5 + int((len(results) / max_pages) * 65))
                self._emit_progress(progress, f"Собрано страниц: {len(results)}/{max_pages}")

            for a in soup.select("a[href]"):
                link = urljoin(current, a["href"])
                parsed = urlparse(link)
                if parsed.scheme in ("http", "https") and parsed.netloc == domain:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)

        return results

    def _build_presentation(self, pages: List[CrawlResult]):
        slides = []
        for i, page in enumerate(pages, start=1):
            html = page.local_file.read_text(encoding="utf-8", errors="ignore")
            safe_html = html.replace("&", "&amp;").replace('"', "&quot;")
            slides.append(
                f"<section class='slide'><h2>{i}. {page.title}</h2>"
                f"<p><a href='{page.url}' target='_blank'>{page.url}</a></p>"
                f"<iframe srcdoc=\"{safe_html}\"></iframe></section>"
            )

        presentation = f"""<!doctype html><html><head><meta charset='utf-8'><title>Локальная презентация</title>
<style>
body {{font-family:Arial,sans-serif;margin:0;background:#0f172a;color:#fff;}}
.container {{display:flex;overflow-x:auto;gap:12px;padding:16px;scroll-snap-type:x mandatory;}}
.slide {{min-width:95%;scroll-snap-align:start;background:#111827;border-radius:12px;padding:12px;}}
a {{color:#60a5fa;}} iframe {{width:100%;height:72vh;background:#fff;border:1px solid #334155;border-radius:8px;}}
</style></head><body><div class='container'>{''.join(slides)}</div></body></html>"""
        PRESENTATION_FILE.write_text(presentation, encoding="utf-8")


HTML_UI = """<!doctype html><html><head><meta charset='utf-8'><title>HTML -> презентация</title><style>
body{margin:0;font-family:Arial,sans-serif;background:#0b1020;color:#e5e7eb}.tabs{display:flex;gap:8px;padding:10px;background:#111827}
.tab-btn{padding:8px 12px;border:none;border-radius:8px;cursor:pointer;background:#1f2937;color:#fff}.tab-btn.active{background:#2563eb}
.tab{display:none;padding:16px;height:calc(100vh - 60px);box-sizing:border-box}.tab.active{display:block}
input,button{padding:10px;border-radius:8px;border:1px solid #334155}button.primary{background:#2563eb;color:#fff;border:none;cursor:pointer}
.progress-wrap{width:100%;background:#1f2937;border-radius:999px;margin-top:16px}.progress{width:0%;height:14px;background:#22c55e;border-radius:999px;transition:width .2s}
#presentationFrame{width:100%;height:90%;border:1px solid #334155;border-radius:8px;background:#fff}.calc{max-width:280px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.calc input{grid-column:1/-1;text-align:right}.calc button{background:#1f2937;color:#fff;border:none}
</style></head><body>
<div class='tabs'><button class='tab-btn active' onclick="openTab('builder',this)">Сборщик</button><button class='tab-btn' onclick="openTab('presentation',this)">Презентация</button><button class='tab-btn' onclick="openTab('calc',this)">Калькулятор</button></div>
<div id='builder' class='tab active'><h2>Сбор HTML в презентацию</h2><input id='urlInput' style='width:68%' placeholder='https://example.com'>
<label style='margin-left:8px;'><input id='noLimit' type='checkbox' onchange='toggleLimit()'> Без лимита</label>
<input id='maxPages' type='number' min='1' max='200' value='30' style='width:120px'>
<button class='primary' onclick='startBuild()'>Старт</button>
<div class='progress-wrap'><div id='progressBar' class='progress'></div></div><p id='progressText'>Ожидание запуска...</p></div>
<div id='presentation' class='tab'><h2>Готовая локальная презентация</h2><iframe id='presentationFrame'></iframe></div>
<div id='calc' class='tab'><h2>Калькулятор</h2><div class='calc'><input id='display' readonly value='0'>
<button onclick="press('7')">7</button><button onclick="press('8')">8</button><button onclick="press('9')">9</button><button onclick="press('/')">÷</button>
<button onclick="press('4')">4</button><button onclick="press('5')">5</button><button onclick="press('6')">6</button><button onclick="press('*')">×</button>
<button onclick="press('1')">1</button><button onclick="press('2')">2</button><button onclick="press('3')">3</button><button onclick="press('-')">−</button>
<button onclick="press('0')">0</button><button onclick="press('.')">.</button><button onclick='calculate()'>=</button><button onclick="press('+')">+</button>
<button onclick='clearDisp()' style='grid-column:1/-1;background:#b91c1c;'>Очистить</button></div></div>
<script>
function openTab(id,btn){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.querySelectorAll('.tab-btn').forEach(t=>t.classList.remove('active'));document.getElementById(id).classList.add('active');btn.classList.add('active');}
function toggleLimit(){const n=document.getElementById('noLimit').checked;const i=document.getElementById('maxPages');i.disabled=n;i.style.opacity=n?'0.5':'1';}
function startBuild(){const url=document.getElementById('urlInput').value.trim();const noLimit=document.getElementById('noLimit').checked;const lim=document.getElementById('maxPages').value.trim();if(!url){alert('Введите URL');return;}window.pywebview.api.build_from_url(url, noLimit ? 'NO_LIMIT' : lim);}
window.updateProgress=(value,text)=>{document.getElementById('progressBar').style.width=`${value}%`;document.getElementById('progressText').textContent=`${text} (${value}%)`;}
window.setStatus=(text)=>{document.getElementById('progressText').textContent=text;}
window.setPresentationPath=(path)=>{document.getElementById('presentationFrame').src=path;}
function press(v){const d=document.getElementById('display');d.value=d.value==='0'?v:d.value+v;} function clearDisp(){document.getElementById('display').value='0';}
function calculate(){const d=document.getElementById('display');try{d.value=String(Function(`'use strict'; return (${d.value})`)());}catch{d.value='Ошибка';}}
</script></body></html>"""


def main():
    api = Api()
    webview.create_window("HTML Presentation Builder", html=HTML_UI, js_api=api, width=1200, height=800)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
