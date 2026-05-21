from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import MarketSnapshot
from .refresh import refresh_all


def _fmt_value(value, decimals):
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def _fmt_change(chg, decimals):
    """Return (display_str, css_class)."""
    if chg is None:
        return "—", ""
    sign = "+" if chg >= 0 else ""
    return f"{sign}{chg:,.{decimals}f}", ("up" if chg >= 0 else "down")


def _card(snap, label, unit, decimals=2, sub_label="前営業日比", sub_tag=None):
    base = {
        "label": label,
        "unit": unit,
        "sub_label": sub_label,
        "sub_tag": sub_tag,
        "is_error": False,
    }
    if snap is None:
        return {**base, "value_display": "—", "change_display": "—", "change_class": ""}
    if snap.status == MarketSnapshot.STATUS_ERROR:
        return {**base, "value_display": "—", "change_display": "—", "change_class": "", "is_error": True}
    chg_str, chg_class = _fmt_change(snap.change_vs_prev_bd, decimals)
    return {
        **base,
        "value_display": _fmt_value(snap.value, decimals),
        "change_display": chg_str,
        "change_class": chg_class,
    }


def _build_chart_data(history, vw=1200, vh=500, pad_x=30, pad_y=40):
    """
    Convert list of {"date", "close"} to SVG drawing data.
    Returns dict with keys:
      stroke_path, area_path  — None when < 2 points
      dots                    — list of (x, y, value) for every data point
    """
    closes = [h["close"] for h in history if h["close"] is not None]
    if not closes:
        return {"stroke_path": None, "area_path": None, "dots": []}

    lo, hi = min(closes), max(closes)
    n = len(closes)

    def _coords(i, v):
        x = vw / 2 if n == 1 else pad_x + (vw - 2 * pad_x) * i / (n - 1)
        y = vh / 2 if hi == lo else vh - pad_y - (vh - 2 * pad_y) * (v - lo) / (hi - lo)
        return x, y

    pts = [_coords(i, v) for i, v in enumerate(closes)]
    dots = [(x, y, v) for (x, y), v in zip(pts, closes)]

    if len(closes) < 2:
        return {"stroke_path": None, "area_path": None, "dots": dots}

    coord_str = " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    stroke_path = f"M{coord_str}"
    area_path = f"{stroke_path} L{pts[-1][0]:.1f},{vh} L{pts[0][0]:.1f},{vh} Z"
    return {"stroke_path": stroke_path, "area_path": area_path, "dots": dots}


@login_required
def dashboard(request):
    refresh_all()

    latest = MarketSnapshot.objects.order_by("-report_date").values("report_date").first()

    if latest is None:
        return render(request, "market/dashboard.html", {
            "cards": [],
            "report_date": None,
            "fetched_at": None,
            "chart_stroke": None,
            "chart_area": None,
            "chart_label": "",
        })

    report_date = latest["report_date"]
    snaps = {s.source_name: s for s in MarketSnapshot.objects.filter(report_date=report_date)}

    cards = [
        _card(snaps.get("ust_30y_yield"),    "UST 30Y",      "%",      decimals=2),
        _card(snaps.get("DJIA Close"),        "DJIA Close",   "pts",    decimals=0),
        _card(snaps.get("USDJPY 8:30"),       "USD/JPY 8:30", "JPY",    decimals=2),
        _card(snaps.get("Gold Settlement"),   "NY Gold",      "USD/oz", decimals=1),
        _card(snaps.get("Tanaka Gold 14:00"), "Tanaka Gold",  "JPY/g",  decimals=0,
              sub_label="14:00 発表分"),
    ]

    # Chart: use accumulated Gold Settlement data from DB (no external requests)
    gold_history = list(
        MarketSnapshot.objects
        .filter(source_name="Gold Settlement", status=MarketSnapshot.STATUS_OK, value__isnull=False)
        .order_by("report_date")
        .values("report_date", "value")
    )
    history = [{"date": r["report_date"], "close": r["value"]} for r in gold_history]
    chart = _build_chart_data(history)
    if history:
        first, last = history[0]["date"], history[-1]["date"]
        chart_label = str(first) if first == last else f"{first} 〜 {last}"
    else:
        chart_label = ""

    fetched_snap = next(iter(snaps.values()), None)
    return render(request, "market/dashboard.html", {
        "cards": cards,
        "report_date": report_date,
        "fetched_at": fetched_snap.fetched_at_jst if fetched_snap else None,
        "chart_stroke": chart["stroke_path"],
        "chart_area": chart["area_path"],
        "chart_dots": chart["dots"],
        "chart_label": chart_label,
    })
