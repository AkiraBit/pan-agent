"""Selection evidence only; the application retrieves all market data from Tushare."""

UNIVERSE_KEY = "tushare-broad-watchlist-v3"
SSE_REPORTS = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/"

# The deduplicated union of the two requested observation lists, grouped by index.
SAMPLE = (
    "510300.SH", "510310.SH", "510330.SH", "159919.SZ",  # CSI 300
    "510050.SH",                                        # SSE 50
    "510500.SH", "159922.SZ",                          # CSI 500
    "512100.SH", "159845.SZ", "560010.SH", "159633.SZ",  # CSI 1000
    "588000.SH", "588080.SH",                          # STAR 50
    "159915.SZ", "159952.SZ",                          # ChiNext
    "159949.SZ",                                       # ChiNext 50
    "512050.SH", "563360.SH", "159338.SZ", "159352.SZ", "159361.SZ",  # CSI A500
    "510210.SH",                                       # SSE Composite
)

# ChiNext 50 is absent from Tushare's benchmark classifications. Check this
# requested fund's tracking index against its issuer: https://www.huaan.com.cn/etf/159949/sgshqd.jsp
SAMPLE_BENCHMARKS = {"159949.SZ": "399673.SZ"}

# 2025 annual reports, section 9.2 of each fund: both named Central Huijin
# entities appear among the listed fund's top holders. This is not a live list.
URLS = {
    "510300.SH": SSE_REPORTS + "510300_20260331_W6CZ.pdf",
    "510310.SH": SSE_REPORTS + "510310_20260331_K996.pdf",
    "510330.SH": SSE_REPORTS + "510330_20260331_X8KM.pdf",
    "159919.SZ": "https://static.cninfo.com.cn/finalpage/2026-03-30/1225041523.PDF",
    "510050.SH": SSE_REPORTS + "510050_20260331_O8IB.pdf",
    "510500.SH": SSE_REPORTS + "510500_20260331_Q394.pdf",
    "159845.SZ": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225052452.PDF",
}
DISCLOSURES = {symbol: {"report_date": "2025-12-31", "url": url} for symbol, url in URLS.items()}
