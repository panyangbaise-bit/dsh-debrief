"""Human-readable crontab descriptions for the Jobs page."""

from scheduler.cron import FIXED_JOB_CRONS, job_cron
from scheduler.cron_text import describe_cron


def test_default_news_crontab_zh():
    text = describe_cron("0 8-22/2 * * *", "zh", "Asia/Shanghai")
    assert text == "每天 08:00–22:00 每 2 小时整点（Asia/Shanghai）"


def test_default_news_crontab_en():
    text = describe_cron("0 8-22/2 * * *", "en", "Asia/Shanghai")
    assert text == ("Every day from 08:00–22:00, every 2 hours on the hour (Asia/Shanghai)")


def test_fixed_job_crons_translate():
    expected = {
        "catalog-sync": "每天 06:10（Asia/Shanghai）",
        "reminders": "*/15 * * * *（Asia/Shanghai）",
        "cleanup": "每天 03:00（Asia/Shanghai）",
    }
    for job_id, sentence in expected.items():
        expr, tz = job_cron(job_id)
        assert (expr, tz) == FIXED_JOB_CRONS[job_id]
        assert describe_cron(expr, "zh", tz) == sentence


def test_prices_cron_is_settings_driven_not_fixed(monkeypatch, tmp_path):
    """Prices polls all market sessions; the cadence is persisted, not fixed."""
    monkeypatch.setattr("scheduler.settings.SETTINGS_PATH", tmp_path / "settings.json")
    from scheduler.settings import get_prices_crontab, set_prices_crontab

    assert get_prices_crontab() == "*/30 * * * *"
    assert job_cron("prices") == ("*/30 * * * *", "Asia/Shanghai")
    assert "prices" not in FIXED_JOB_CRONS
    set_prices_crontab("*/15 1-5 * * *")
    assert job_cron("prices") == ("*/15 1-5 * * *", "Asia/Shanghai")
    assert describe_cron("*/15 1-5 * * *", "zh", "Asia/Shanghai") == (
        "*/15 1-5 * * *（Asia/Shanghai）"
    )


def test_monthly_ordinal_en():
    assert describe_cron("0 21 1 * *", "en", "Asia/Shanghai") == (
        "Every month on the 1st at 21:00 (Asia/Shanghai)"
    )


def test_unsupported_expr_falls_back_to_raw():
    assert describe_cron("0 8-22/2 * * 1", "zh", "Asia/Shanghai") == (
        "0 8-22/2 * * 1（Asia/Shanghai）"
    )


def test_weekday_news_schedule_is_readable():
    assert describe_cron("0 8-22/4 * * mon-fri", "zh") == "周一至周五 08:00–22:00 每 4 小时整点"
    assert (
        describe_cron("0 8-22/4 * * mon-fri", "en")
        == "Monday–Friday from 08:00–22:00, every 4 hours on the hour"
    )
    assert describe_cron("0 7 * * 0-4", "en") == "Monday–Friday at 07:00"
