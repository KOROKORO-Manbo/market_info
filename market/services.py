"""
Financial data scraping helpers.
Each fetch_* function returns a dict with keys:
  source_name, source_url, value, unit, note
  (treasury also returns a "detail" key with sub-values)
"""

import re
import requests
import pandas as pd
from lxml import html as lxml_html
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/TextView?type=daily_treasury_yield_curve"
)
TANAKA_URL = "https://gold.tanaka.co.jp/commodity/souba/index.php"

YFJP_DJI_URL    = "https://finance.yahoo.co.jp/quote/%5EDJI"
YFJP_TYX_URL    = "https://finance.yahoo.co.jp/quote/%5ETYX"
YFJP_USDJPY_URL = "https://finance.yahoo.co.jp/quote/USDJPY=X"
GOLD_API_URL    = "https://query2.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def jst_now() -> datetime:
    return datetime.now(JST)


def previous_business_day(date):
    return (pd.Timestamp(date).normalize() - pd.tseries.offsets.BDay(1)).date()


def safe_float(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("¥", "").replace("%", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _extract_yfjp_index_price(html):
    """Return (value_str, change_str) from a Yahoo Finance Japan index quote page."""
    for block in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S):
        if 'changePrice' not in block:
            continue
        try:
            unescaped = block.encode('raw_unicode_escape').decode('unicode_escape')
        except Exception:
            unescaped = block.replace('\\"', '"')
        m = re.search(r'"price"\s*:\s*\{[^}]*?"value"\s*:\s*"([0-9,\.]+)"', unescaped)
        if m:
            chg = re.search(r'"price"\s*:\s*\{[^}]*?"changePrice"\s*:\s*"([+-]?[0-9,\.]+)"', unescaped)
            return m.group(1), (chg.group(1) if chg else None)
    return None, None


def fetch_treasury_yield(target_date):
    tables = pd.read_html(TREASURY_URL)
    df = None
    for t in tables:
        cols = [str(c).lower() for c in t.columns]
        if any("date" in c for c in cols):
            df = t.copy()
            break
    if df is None:
        raise RuntimeError("Treasury table not found")

    date_col = [c for c in df.columns if "Date" in str(c) or "date" in str(c).lower()][0]
    df[date_col] = pd.to_datetime(df[date_col]).dt.date
    row = df[df[date_col] == target_date]
    if row.empty:
        row = df.iloc[[-1]]

    out = row.iloc[0].to_dict()
    return {
        "source_name": "UST 10Y/20Y",
        "source_url": TREASURY_URL,
        "value": None,
        "unit": "%",
        "note": f"treasury_date={out.get(date_col)}",
        "detail": {
            "ust_10y_yield": safe_float(out.get("10 Yr")),
            "ust_20y_yield": safe_float(out.get("20 Yr")),
        },
    }


def fetch_ust30y_yfjp(target_date):
    """米国30年国債利回りを Yahoo Finance Japan (^TYX) から取得する。"""
    r = requests.get(YFJP_TYX_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    value_s, change_s = _extract_yfjp_index_price(r.text)
    if value_s is None:
        raise RuntimeError("UST 30Y price not found on Yahoo Finance Japan (^TYX)")
    value = safe_float(value_s)
    change = safe_float(change_s)
    prev = (value - change) if (value is not None and change is not None) else None
    change_pct = (change / prev * 100) if (change is not None and prev) else None
    return {
        "source_name": "ust_30y_yield",
        "source_url": YFJP_TYX_URL,
        "value": value,
        "unit": "%",
        "note": f"Yahoo Finance Japan / ^TYX / {target_date}",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }


def fetch_dji_close_yfjp(target_date):
    """ダウ平均終値を Yahoo Finance Japan (^DJI) から取得する。"""
    r = requests.get(YFJP_DJI_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    value_s, change_s = _extract_yfjp_index_price(r.text)
    if value_s is None:
        raise RuntimeError("DJI price not found on Yahoo Finance Japan (^DJI)")
    value = safe_float(value_s)
    change = safe_float(change_s)
    prev = (value - change) if (value is not None and change is not None) else None
    change_pct = (change / prev * 100) if (change is not None and prev) else None
    return {
        "source_name": "DJIA Close",
        "source_url": YFJP_DJI_URL,
        "value": value,
        "unit": "index",
        "note": f"Yahoo Finance Japan / ^DJI / {target_date}",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }


def fetch_usdjpy_yfjp(target_date):
    """ドル円レートを Yahoo Finance Japan (USDJPY=X) から取得する。"""
    r = requests.get(YFJP_USDJPY_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    bid_m = re.search(r'"bid"\s*:\s*"([0-9,\.]+)"', r.text)
    if not bid_m:
        raise RuntimeError("USDJPY bid not found on Yahoo Finance Japan")
    value = safe_float(bid_m.group(1))
    chg_m = re.search(r'"changePrice"\s*:\s*"([+-]?[0-9,\.]+)"', r.text)
    change = safe_float(chg_m.group(1)) if chg_m else None
    prev = (value - change) if (value is not None and change is not None) else None
    change_pct = (change / prev * 100) if (change is not None and prev) else None
    return {
        "source_name": "USDJPY 8:30",
        "source_url": YFJP_USDJPY_URL,
        "value": value,
        "unit": "JPY/USD",
        "note": f"Yahoo Finance Japan / USDJPY=X / {target_date}",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }


def fetch_gold_yf_api(target_date):
    """NY金先物（期近限月）終値を Yahoo Finance API (GC=F) から取得する。"""
    r = requests.get(GOLD_API_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    result = (data.get('chart') or {}).get('result') or []
    if not result:
        raise RuntimeError("Gold futures data not found in Yahoo Finance API response")
    meta = result[0]['meta']
    price = meta.get('regularMarketPrice')
    prev_close = meta.get('chartPreviousClose')
    if price is None:
        raise RuntimeError("Gold futures regularMarketPrice not found")
    price = float(price)
    change = (price - float(prev_close)) if prev_close is not None else None
    change_pct = (change / float(prev_close) * 100) if (change is not None and prev_close) else None
    return {
        "source_name": "Gold Settlement",
        "source_url": "https://finance.yahoo.co.jp/",
        "value": price,
        "unit": "USD/oz",
        "note": f"Yahoo Finance API / GC=F / {target_date}",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }


def fetch_tanaka_gold_1400(target_date):
    r = requests.get(TANAKA_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    tree = lxml_html.fromstring(r.content)

    # 更新時刻: h3/span
    update_time_nodes = tree.xpath("/html/body/div[2]/div[2]/div/h3/span")
    update_time = update_time_nodes[0].text_content().strip() if update_time_nodes else "店頭小売価格（税込）"

    # 店頭小売価格（税込）: tbody なしで tr[2]/td[2]
    _xpath_base = (
        "/html/body/div[2]/div[2]/div"
        "/div[@class='contents_inner']/table/tr[2]"
    )
    price_nodes = tree.xpath(f"{_xpath_base}/td[2]")
    if not price_nodes:
        raise RuntimeError("Tanaka gold price not found at XPath")

    price = safe_float(price_nodes[0].text_content())
    if price is None:
        raise RuntimeError("Tanaka gold price parse failed")

    chg_nodes = tree.xpath(f"{_xpath_base}/td[3]")
    change = safe_float(chg_nodes[0].text_content()) if chg_nodes else None
    change_pct = (
        (change / (price - change) * 100)
        if (change is not None and price != change)
        else None
    )

    return {
        "source_name": "Tanaka Gold 14:00",
        "source_url": TANAKA_URL,
        "value": price,
        "unit": "JPY/g",
        "note": update_time,
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }
