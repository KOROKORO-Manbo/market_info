"""
Financial data scraping helpers.
Each fetch_* function returns a dict with keys:
  source_name, source_url, value, unit, note
  (treasury also returns a "detail" key with sub-values)
"""

import re
import json
import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from lxml import html as lxml_html
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/TextView?type=daily_treasury_yield_curve"
)
DJI_TICKER = "^DJI"
USDJPY_TICKER = "USDJPY=X"
GOLD_TICKER = "GC=F"
USDJPY_URL = "https://finance.yahoo.com/quote/USDJPY=X/"
CME_GOLD_URL = "https://finance.yahoo.com/quote/GC=F/"
TANAKA_URL = "https://gold.tanaka.co.jp/commodity/souba/index.php"
SBI_PAGE_URL = (
    "https://www.sbisec.co.jp/ETGate/?_ControlID=WPLETmgR001Control"
    "&_PageID=WPLETmgR001Mdtl20&_DataStoreID=DSWPLETmgR001Control"
    "&_ActionID=DefaultAID&burl=iris_indexDetail&cat1=market&cat2=index"
    "&dir=tl1-idxdtl%7Ctl2-US30YT%3DXX%7Ctl5-jpn&file=index.html&getFlg=on"
)
SBI_DATA_BASE = "https://vc.iris.sbisec.co.jp/vc/psdata/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
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


def _sbi_fixed_qs():
    """Fetch SBI page and extract the FIXED_QS (hash + params) dynamically."""
    r = requests.get(SBI_PAGE_URL, headers=HEADERS, timeout=20)
    r.encoding = "shift_jis"
    m = re.search(r"var FIXED_QS\s*=\s*'([^']+)'", r.text)
    if not m:
        raise RuntimeError("SBI FIXED_QS not found in page")
    return m.group(1)  # e.g. "?hash=xxx&investor=visitor&callback=?"


def fetch_ust30y_sbi(target_date):
    """Fetch US 30Y Treasury yield from SBI Securities JSONP API."""
    fixed_qs = _sbi_fixed_qs()
    api_qs = fixed_qs.replace("callback=?", "callback=parseResponse")
    api_url = f"{SBI_DATA_BASE}listAndChart.do{api_qs}&ricCode=US30YT=XX"

    r = requests.get(
        api_url,
        headers={**HEADERS, "Referer": "https://www.sbisec.co.jp/"},
        timeout=20,
    )
    r.encoding = "shift_jis"

    price_m = re.search(r"price\s*:\s*'([0-9.]+)'", r.text)
    if not price_m:
        raise RuntimeError("UST 30Y price not found in SBI response")
    price = float(price_m.group(1))

    # netChange は "<span class=\"md-down\">-0.004</span>" 形式
    chg_m = re.search(r"netChange\s*:\s*'[^']*?([+-]?\d+\.\d+)[^']*?'", r.text)
    change = float(chg_m.group(1)) if chg_m else None
    change_pct = (change / (price - change) * 100) if (change is not None and price != change) else None

    return {
        "source_name": "ust_30y_yield",
        "source_url": SBI_PAGE_URL,
        "value": price,
        "unit": "%",
        "note": f"SBI Securities / US30YT=XX / {target_date}",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }


def fetch_dji_close(target_date):
    close, actual_date = _yf_close(DJI_TICKER, target_date)
    return {
        "source_name": "DJIA Close",
        "source_url": "https://finance.yahoo.com/quote/%5EDJI/history/",
        "value": close,
        "unit": "index",
        "note": f"close_date={actual_date}",
    }


def _yf_close(ticker, target_date, retries=3, base_wait=30):
    """
    Download daily close for ticker via Ticker.history(), with retry on rate limit.
    Uses Ticker API (different endpoint from yf.download) to reduce rate limit risk.
    """
    last_err = None
    for attempt in range(retries + 1):
        if attempt > 0:
            time.sleep(base_wait * attempt)
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="15d", interval="1d", auto_adjust=False)
            if df.empty:
                raise RuntimeError(f"{ticker}: no data returned from yfinance")
            df = df.reset_index()
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            row = df[df["Date"] == target_date]
            if row.empty:
                row = df.iloc[[-1]]
            return float(row["Close"].iloc[0]), row["Date"].iloc[0]
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if any(k in msg for k in ("rate", "429", "too many")):
                continue  # retry
            raise
    raise last_err


def fetch_usdjpy_0830(target_date):
    close, actual_date = _yf_close(USDJPY_TICKER, target_date)
    return {
        "source_name": "USDJPY 8:30",
        "source_url": USDJPY_URL,
        "value": close,
        "unit": "JPY/USD",
        "note": f"close_date={actual_date} (via yfinance)",
    }


def fetch_cme_gold_settlement(target_date):
    close, actual_date = _yf_close(GOLD_TICKER, target_date)
    return {
        "source_name": "Gold Settlement",
        "source_url": CME_GOLD_URL,
        "value": close,
        "unit": "USD/oz",
        "note": f"close_date={actual_date} (GC=F via yfinance)",
    }


def fetch_gold_history(days=30):
    """Return list of {"date": date, "close": float} for chart rendering."""
    t = yf.Ticker(GOLD_TICKER)
    df = t.history(period=f"{days + 10}d", interval="1d", auto_adjust=False)
    if df.empty:
        return []
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df.dropna(subset=["Close"]).tail(days)
    return [
        {"date": row["Date"], "close": float(row["Close"])}
        for _, row in df.iterrows()
    ]


def fetch_tanaka_gold_1400(target_date):
    r = requests.get(TANAKA_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    tree = lxml_html.fromstring(r.content)

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
        "note": "店頭小売価格（税込）",
        "change_vs_prev_bd": change,
        "change_vs_prev_bd_pct": change_pct,
    }
