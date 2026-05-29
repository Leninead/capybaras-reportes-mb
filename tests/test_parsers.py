"""Tests for parsers — use sample CSV fixtures."""
import os
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


# ── Business Report ────────────────────────────────────────────────────────────

class TestBusinessReport:
    def test_basic_aggregation(self):
        from app.parsers.business_report import parse
        data = parse(read_fixture("business_report_sample.csv"))
        acc = data.account

        # Revenue B2C = total - B2B
        # totals: 7200+5600+2700+3200+2400 = 21100
        # b2b:      300+ 175+   0+   0+   0 =   475
        assert abs(acc.revenue - (21100 - 475)) < 0.01

        # Units B2C = 560 - 15 = 545
        assert acc.ordered_units == 545

        # Sessions = 1200+800+600+400+300 = 3300
        assert acc.sessions == 3300

        # Page views = 1800+1200+900+600+450 = 4950
        assert acc.page_views == 4950

    def test_conv_pct_calculated(self):
        from app.parsers.business_report import parse
        data = parse(read_fixture("business_report_sample.csv"))
        acc = data.account
        expected_conv = 545 / 3300 * 100
        assert abs(acc.conv_pct - expected_conv) < 0.01

    def test_avg_retail_calculated(self):
        from app.parsers.business_report import parse
        data = parse(read_fixture("business_report_sample.csv"))
        acc = data.account
        expected_avg = 20625 / 545
        assert abs(acc.avg_retail - expected_avg) < 0.01

    def test_buybox_weighted_avg(self):
        from app.parsers.business_report import parse
        data = parse(read_fixture("business_report_sample.csv"))
        assert data.account.buybox_win_pct is not None
        # Should be between 97 and 100
        assert 97 <= data.account.buybox_win_pct <= 100

    def test_missing_required_column_raises(self):
        from app.parsers.business_report import parse
        bad_csv = b"ASIN,Title\nB001,Product A\n"
        with pytest.raises(ValueError, match="columnas requeridas"):
            parse(bad_csv)

    def test_empty_file_raises(self):
        from app.parsers.business_report import parse
        # Valid header but no rows
        csv = b"Sessions,Page Views,Units Ordered,Ordered Product Sales\n"
        with pytest.raises(ValueError, match="vacío"):
            parse(csv)

    def test_no_b2b_columns_still_works(self):
        from app.parsers.business_report import parse
        csv = (
            b"Sessions,Page Views,Units Ordered,Ordered Product Sales\n"
            b"100,150,20,\"$500.00\"\n"
            b"200,300,40,\"$1000.00\"\n"
        )
        data = parse(csv)
        assert data.account.sessions == 300
        assert data.account.ordered_units == 60
        assert abs(data.account.revenue - 1500) < 0.01

    def test_currency_with_commas_and_dollar(self):
        from app.parsers.utils import parse_number
        assert parse_number("$1,234.56") == pytest.approx(1234.56)
        assert parse_number("12.5%") == pytest.approx(12.5)
        assert parse_number("1,234") == pytest.approx(1234)
        assert parse_number("") is None
        assert parse_number("--") is None
        assert parse_number("N/A") is None


# ── Ads Report ────────────────────────────────────────────────────────────────

class TestAdsReport:
    def test_basic_aggregation(self):
        from app.parsers.ads_report import parse
        data = parse(read_fixture("ads_report_sample.csv"), "ads_report_sample.csv")
        ads = data.ads

        # Spend = 99+180+90+45 = 414
        assert abs(ads.ad_spend - 414) < 0.01

        # Sales = 990+1800+720+360 = 3870
        assert abs(ads.ad_sales - 3870) < 0.01

        # Impressions = 12000+30000+45000+20000 = 107000
        assert ads.impressions == 107000

        # Clicks = 180+250+150+100 = 680
        assert ads.clicks == 680

    def test_derived_metrics(self):
        from app.parsers.ads_report import parse
        data = parse(read_fixture("ads_report_sample.csv"), "ads_report_sample.csv")
        ads = data.ads

        # ACOS = spend/sales*100 = 414/3870*100
        assert abs(ads.acos_pct - (414 / 3870 * 100)) < 0.01

        # ROAS = sales/spend
        assert abs(ads.roas - (3870 / 414)) < 0.01

        # CPC = spend/clicks = 414/680
        assert abs(ads.cpc - (414 / 680)) < 0.01

    def test_ntb_aggregation(self):
        from app.parsers.ads_report import parse
        data = parse(read_fixture("ads_report_sample.csv"), "ads_report_sample.csv")
        # NTB orders = 5+12+8+3 = 28
        assert data.ads.ntb_units == 28

    def test_missing_required_column_raises(self):
        from app.parsers.ads_report import parse
        bad = b"Campaign Name,Sales\nCampaign A,$100\n"
        with pytest.raises(ValueError, match="columnas requeridas"):
            parse(bad, "bad.csv")


# ── Delta Engine ──────────────────────────────────────────────────────────────

class TestDeltas:
    def test_pct_change_positive(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("revenue", 1100, 1000)
        assert abs(d["value"] - 10.0) < 0.01
        assert d["display"] == "+10.0%"
        assert d["is_good"] is True

    def test_pct_change_negative(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("revenue", 900, 1000)
        assert d["is_good"] is False

    def test_lower_is_better_acos(self):
        from app.engine.deltas import calc_delta
        # ACOS went down → good
        d = calc_delta("acos_pct", 8, 12)
        assert d["value"] == pytest.approx(-4.0)
        assert d["is_good"] is True
        assert "ppt" in d["display"]

    def test_lower_is_better_ad_spend(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("ad_spend", 500, 1000)
        assert d["is_good"] is True  # spending less is good

    def test_percent_type_uses_ppt(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("conv_pct", 12.5, 10.0)
        assert "ppt" in d["display"]
        assert abs(d["value"] - 2.5) < 0.01

    def test_ratio_type_absolute_diff(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("roas", 8.5, 7.0)
        assert "x" in d["display"]
        assert abs(d["value"] - 1.5) < 0.01

    def test_zero_prior_returns_nd(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("revenue", 500, 0)
        assert d["display"] == "n/d"
        assert d["value"] is None

    def test_base_baja_detection(self):
        from app.engine.deltas import calc_delta
        # prior=10, current=5000 → +49900%, prior is tiny
        d = calc_delta("revenue", 5000, 10)
        assert d["base_baja"] is True
        assert d["display"] == "base baja"

    def test_none_values(self):
        from app.engine.deltas import calc_delta
        d = calc_delta("revenue", None, 1000)
        assert d["display"] == "N/A"
        d2 = calc_delta("revenue", 1000, None)
        assert d2["display"] == "N/A"


# ── Derived KPIs ──────────────────────────────────────────────────────────────

class TestDerivedKPIs:
    def test_compute_derived(self):
        from app.engine.kpis import AccountSummary, AdPerformance, compute_derived
        acc = AccountSummary(revenue=10000, ordered_units=200)
        ads = AdPerformance(ad_spend=500, ad_sales=5000, clicks=100, orders=20)
        compute_derived(acc, ads)
        assert abs(acc.avg_retail - 50.0) < 0.01
        assert abs(ads.acos_pct - 10.0) < 0.01
        assert abs(ads.roas - 10.0) < 0.01
        assert abs(ads.tacos_pct - 5.0) < 0.01
        assert abs(ads.troas - 20.0) < 0.01
        assert abs(ads.cpc - 5.0) < 0.01
        assert abs(ads.cpa - 25.0) < 0.01
        assert abs(ads.conv_pct_ads - 20.0) < 0.01
