import re
import json
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
DJI_TICKER = "^DJI"
USDJPY_URL = "https://jp.reuters.com/markets/quote/USDJPY=X/"
CME_GOLD_URL = "https://www.cmegroup.com/markets/metals/precious/gold.settlements.html"
TANAKA_URL = "https://gold.tanaka.co.jp/commodity/souba/english/index.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def jst_now():
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
        "source_name": "UST 10Y/20Y/30Y",
        "source_url": TREASURY_URL,
        "value": None,
        "unit": "%",
        "note": f"treasury_date={out.get(date_col)}",
        "detail": {
            "ust_10y_yield": safe_float(out.get("10 Yr")),
            "ust_20y_yield": safe_float(out.get("20 Yr")),
            "ust_30y_yield": safe_float(out.get("30 Yr")),
        }
    }

def fetch_dji_close(target_date):
    start = pd.Timestamp(target_date) - pd.Timedelta(days=10)
    end = pd.Timestamp(target_date) + pd.Timedelta(days=2)
    df = yf.download(DJI_TICKER, start=start.date(), end=end.date(), interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError("DJI data not found")
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    row = df[df["Date"] == target_date]
    if row.empty:
        row = df.iloc[[-1]]
    close = float(row.iloc[0]["Close"])
    return {
        "source_name": "DJIA Close",
        "source_url": f"https://finance.yahoo.com/quote/%5EDJI/history/",
        "value": close,
        "unit": "index",
        "note": f"close_date={row.iloc[0]['Date']}"
    }

def fetch_usdjpy_0830(target_date):
    url = USDJPY_URL
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    text = r.text
    candidates = re.findall(r'USDJPY[^0-9]{0,40}(\d+\.\d+)', text)
    value = safe_float(candidates[0]) if candidates else None
    if value is None:
        m = re.search(r'(\d+\.\d+)', text)
        value = safe_float(m.group(1)) if m else None
    if value is None:
        raise RuntimeError("USDJPY value not found")
    return {
        "source_name": "USDJPY 8:30",
        "source_url": url,
        "value": value,
        "unit": "JPY/USD",
        "note": "Reuters page snapshot; replace with API if available"
    }

def fetch_cme_gold_settlement(target_date):
    trade_date = pd.Timestamp(target_date).strftime("%m/%d/%Y")
    url = f"https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/GC/FUT?tradeDate={trade_date}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json() if "json" in r.headers.get("content-type","").lower() else json.loads(r.text)
    rows = data.get("settlements") or data.get("settlement") or data.get("data") or []
    if not rows:
        raise RuntimeError("CME settlements not found")
    row = rows[0]
    settlement = safe_float(row.get("settlementPrice") or row.get("settlement") or row.get("price"))
    if settlement is None:
        raise RuntimeError("CME settlement price not found")
    return {
        "source_name": "Gold Settlement",
        "source_url": url,
        "value": settlement,
        "unit": "USD/oz",
        "note": f"trade_date={trade_date}"
    }

def fetch_tanaka_gold_1400(target_date):
    r = requests.get(TANAKA_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    price = None
    buy = None

    m = re.search(r"GOLD.*?\n\|.*?\n\|.*?\|([0-9,]+)\s*yen\|([+-]?[0-9,]+)\s*yen\|([0-9,]+)\s*yen\|([+-]?[0-9,]+)\s*yen\|", html, re.S | re.I)
    if m:
        price = safe_float(m.group(1))
        buy = safe_float(m.group(3))
    else:
        t = re.search(r"Price information \(As of at 14:00 on .*?\)\s*\|\|TANAKA retail selling price.*?\|\n\|--\|--\|--\|--\|--\|\n\|GOLD\|([0-9,]+) yen\|([+-]?[0-9,]+) yen\|([0-9,]+) yen\|([+-]?[0-9,]+) yen\|", text, re.S | re.I)
        if t:
            price = safe_float(t.group(1))
            buy = safe_float(t.group(3))

    if price is None:
        price_match = re.search(r"\|GOLD\|([0-9,]+)\s*yen\|", html, re.I)
        if price_match:
            price = safe_float(price_match.group(1))

    if price is None:
        raise RuntimeError("Tanaka gold price not found")

    return {
        "source_name": "Tanaka Gold 14:00",
        "source_url": TANAKA_URL,
        "value": price,
        "unit": "JPY/g",
        "note": "14:00 sell price"
    }

def build_row(source_name, source_url, value, prev_value, unit="", note="", status="ok", error_message=""):
    chg = None if value is None or prev_value is None else value - prev_value
    pct = None if value is None or prev_value in (None, 0) else (chg / prev_value) * 100
    return {
        "report_date": jst_now().date(),
        "fetched_at_jst": jst_now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_name": source_name,
        "source_url": source_url,
        "value": value,
        "unit": unit,
        "change_vs_prev_bd": chg,
        "change_vs_prev_bd_pct": pct,
        "note": note,
        "status": status,
        "error_message": error_message,
    }

def main():
    report_date = jst_now().date()
    prev_bd = previous_business_day(report_date)

    rows = []

    try:
        treasury = fetch_treasury_yield(prev_bd)
        for k, v in treasury["detail"].items():
            rows.append(build_row(k, treasury["source_url"], v, None, unit="%", note=treasury["note"]))
    except Exception as e:
        rows.append(build_row("UST 10Y/20Y/30Y", TREASURY_URL, None, None, unit="%", status="error", error_message=str(e)))

    try:
        dji = fetch_dji_close(prev_bd)
        rows.append(build_row("DJIA Close", dji["source_url"], dji["value"], None, unit="index", note=dji["note"]))
    except Exception as e:
        rows.append(build_row("DJIA Close", f"https://finance.yahoo.com/quote/%5EDJI/history/", None, None, unit="index", status="error", error_message=str(e)))

    try:
        fx = fetch_usdjpy_0830(prev_bd)
        rows.append(build_row("USDJPY 8:30", fx["source_url"], fx["value"], None, unit="JPY/USD", note=fx["note"]))
    except Exception as e:
        rows.append(build_row("USDJPY 8:30", USDJPY_URL, None, None, unit="JPY/USD", status="error", error_message=str(e)))

    try:
        gold = fetch_cme_gold_settlement(prev_bd)
        rows.append(build_row("Gold Settlement", gold["source_url"], gold["value"], None, unit="USD/oz", note=gold["note"]))
    except Exception as e:
        rows.append(build_row("Gold Settlement", CME_GOLD_URL, None, None, unit="USD/oz", status="error", error_message=str(e)))

    try:
        tanaka = fetch_tanaka_gold_1400(prev_bd)
        rows.append(build_row("Tanaka Gold 14:00", tanaka["source_url"], tanaka["value"], None, unit="JPY/g", note=tanaka["note"]))
    except Exception as e:
        rows.append(build_row("Tanaka Gold 14:00", TANAKA_URL, None, None, unit="JPY/g", status="error", error_message=str(e)))

    df = pd.DataFrame(rows)
    df.to_csv("output/daily_market_snapshot.csv", index=False, encoding="utf-8-sig")
    return df

if __name__ == "__main__":
    df = main()