"""
市場情緒資料抓取腳本（GitHub Actions 用）
輸出：data/latest.json
"""
import json, os, time
from datetime import datetime
import requests, urllib3
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MM_URL = (
    "https://www.macromicro.me/collections/46/tw-stock-relative/"
    "128747/taiwan-mm-fear-and-greed-index-vs-taiex"
)
CNN_FG_URL     = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_ACTIVE_URL = "https://production.dataviz.cnn.io/markets/stocks/actives/10/2"
CNN_HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept":  "application/json",
    "Referer": "https://edition.cnn.com/",
    "Origin":  "https://edition.cnn.com",
}

CHECK_JS = """
() => {
    try {
        if (!window.Highcharts || !window.Highcharts.charts) return null;
        const chart = window.Highcharts.charts.find(c => c);
        if (!chart) return null;
        const s = chart.userOptions && chart.userOptions.series;
        if (!s || s.length < 2) return null;
        if (!s[0].data || s[0].data.length < 100) return null;
        const d0 = s[0].data, d1 = s[1].data;
        return {
            fear_date:   new Date(d0[d0.length-1][0]).toISOString().split('T')[0],
            fear_value:  d0[d0.length-1][1],
            fear_prev:   d0[d0.length-2][1],
            taiex_date:  new Date(d1[d1.length-1][0]).toISOString().split('T')[0],
            taiex_value: d1[d1.length-1][1],
            taiex_prev:  d1[d1.length-2][1],
            fear_data:   d0,
            taiex_data:  d1
        };
    } catch(e) { return null; }
}
"""


def fetch_mm():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--window-position=-2000,0",
                    "--window-size=1280,800",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--mute-audio",
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page.goto(MM_URL, wait_until="load", timeout=60000)

            result = None
            for _ in range(30):
                time.sleep(2)
                try:
                    result = page.evaluate(CHECK_JS)
                    if result and len(result.get("fear_data", [])) >= 100:
                        break
                except Exception:
                    pass
                result = None

            browser.close()
            return result
    except Exception as e:
        print(f"[MM] {e}")
        return None


def prepare_series(raw):
    seen = {}
    for point in raw:
        ts_ms, val = point[0], point[1]
        dt_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        seen[dt_str] = round(float(val), 2)
    return [{"date": k, "value": v} for k, v in sorted(seen.items())]


def fetch_cnn():
    try:
        r = requests.get(CNN_FG_URL, headers=CNN_HEADERS, verify=False, timeout=15)
        r.raise_for_status()
        data = r.json()
        fg = data.get("fear_and_greed", {})
        hist_raw = data.get("fear_and_greed_historical", {}).get("data", [])
        historical = []
        for item in hist_raw:
            dt = datetime.fromtimestamp(item.get("x", 0) / 1000).strftime("%Y-%m-%d")
            historical.append({"date": dt, "score": round(float(item.get("y", 0)), 1)})
        historical.sort(key=lambda x: x["date"])
        return {
            "score":      round(float(fg.get("score", 0)), 1),
            "prev_close": round(float(fg.get("previous_close", 0)), 1),
            "prev_week":  round(float(fg.get("previous_1_week", 0)), 1),
            "rating":     fg.get("rating", "").replace("_", " ").title(),
            "date":       fg.get("timestamp", "")[:10],
            "historical": historical,
        }
    except Exception as e:
        print(f"[CNN] {e}")
        return None


def fetch_actives():
    try:
        r = requests.get(CNN_ACTIVE_URL, headers=CNN_HEADERS, verify=False, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[CNN actives] {e}")
        return []


def main():
    os.makedirs("data", exist_ok=True)

    existing = {}
    try:
        with open("data/latest.json", encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        pass

    print("Fetching CNN data...")
    cnn = fetch_cnn()

    print("Fetching CNN actives...")
    actives = []
    for s in fetch_actives():
        try:
            chg = float(s.get("price_change_from_prev_close", 0))
            pct = float(s.get("percent_change_from_prev_close", 0)) * 100
            actives.append({
                "name":   s.get("name", "")[:32],
                "symbol": s.get("symbol", ""),
                "price":  round(float(s.get("current_price", 0)), 2),
                "chg":    round(chg, 2),
                "pct":    round(pct, 2),
                "h52":    str(s.get("high_52_week", "")),
                "l52":    str(s.get("low_52_week", "")),
            })
        except Exception:
            pass

    print("Fetching MM data (Playwright + Xvfb)...")
    mm_raw = fetch_mm()

    mm = existing.get("mm")
    if mm_raw:
        mm = {
            "fear_value":   round(float(mm_raw["fear_value"]), 1),
            "fear_prev":    round(float(mm_raw["fear_prev"]), 1),
            "fear_date":    mm_raw["fear_date"],
            "taiex_value":  round(float(mm_raw["taiex_value"]), 0),
            "taiex_prev":   round(float(mm_raw["taiex_prev"]), 0),
            "taiex_date":   mm_raw["taiex_date"],
            "fear_series":  prepare_series(mm_raw["fear_data"]),
            "taiex_series": prepare_series(mm_raw["taiex_data"]),
        }
    else:
        print("[MM] 失敗，使用上次快取資料")

    result = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cnn":        cnn or existing.get("cnn"),
        "actives":    actives or existing.get("actives", []),
        "mm":         mm,
    }

    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"完成。CNN={result['cnn'] and result['cnn']['score']}，MM={mm and mm['fear_value']}")


if __name__ == "__main__":
    main()
