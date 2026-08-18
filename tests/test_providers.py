import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from llm_org_cost_monitor.dates import DateRange, range_for_period
from llm_org_cost_monitor.providers import (
    AnthropicCostClient,
    OpenAICostClient,
    ProviderAPIError,
    _utc_today,
)


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_parses_costs_and_project_names():
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1", "name": "Lab"}], "has_more": False})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "start_time": 1782864000,
                        "end_time": 1782950400,
                        "results": [
                            {
                                "amount": {"value": 1.23, "currency": "usd"},
                                "project_id": "proj_1",
                                "api_key_id": "key_1",
                                "line_item": "Responses API",
                            }
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            },
        )

    client = OpenAICostClient("sk-admin-test", client=make_client(handler))
    records, warnings = client.fetch_costs(DateRange(date(2026, 7, 1), date(2026, 7, 2)))

    assert warnings == []
    assert records[0].amount == Decimal("1.23")
    assert records[0].currency == "USD"
    assert records[0].project_name == "Lab"
    assert records[0].api_key_id == "key_1"
    assert records[0].line_item == "Responses API"
    assert "group_by=project_id" in seen_urls[-1]
    assert "group_by=api_key_id" in seen_urls[-1]
    assert "group_by=line_item" in seen_urls[-1]


def test_openai_paginates_costs():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("page"))
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [], "has_more": False})
        has_page = request.url.params.get("page") == "next"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "start_time": 1782864000,
                        "results": [{"amount": {"value": 1 if not has_page else 2, "currency": "usd"}}],
                    }
                ],
                "has_more": not has_page,
                "next_page": "next" if not has_page else None,
            },
        )

    client = OpenAICostClient("sk-admin-test", client=make_client(handler))
    records, _ = client.fetch_costs(DateRange(date(2026, 7, 1), date(2026, 7, 3)))

    assert [record.amount for record in records] == [Decimal("1"), Decimal("2")]
    assert calls[-2:] == [None, "next"]


def test_anthropic_parses_costs_cents_to_usd():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/workspaces":
            return httpx.Response(200, json={"data": [{"id": "wrk_1", "name": "Product"}], "has_more": False})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "starting_at": "2026-07-01T00:00:00Z",
                        "results": [
                            {
                                "amount": "1234.56",
                                "currency": "USD",
                                "workspace_id": "wrk_1",
                                "description": "Input Tokens",
                            }
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            },
        )

    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(handler))
    records, warnings = client.fetch_costs(DateRange(date(2026, 7, 1), date(2026, 7, 2)))

    assert warnings == []
    assert records[0].amount == Decimal("12.345600")
    assert records[0].workspace_name == "Product"
    assert records[0].line_item == "Input Tokens"
    assert records[0].raw_amount == "1234.56"


@pytest.mark.parametrize("status", [401, 429])
def test_provider_errors(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope"}})

    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(handler))
    with pytest.raises(ProviderAPIError) as exc:
        client.fetch_costs(DateRange(date(2026, 7, 1), date(2026, 7, 2)))

    assert exc.value.status_code == status
    assert "nope" in exc.value.message


def test_empty_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "has_more": False})

    client = OpenAICostClient("sk-admin-test", client=make_client(handler))
    records, warnings = client.fetch_costs(DateRange(date(2026, 7, 1), date(2026, 7, 2)))

    assert records == []
    assert warnings == []


def _cost_report_handler(seen):
    """Handler recording cost_report query params; fails the test if that path is hit unexpectedly."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/workspaces":
            return httpx.Response(200, json={"data": [], "has_more": False})
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "has_more": False, "next_page": None})

    return handler


def test_anthropic_skips_request_when_range_has_no_complete_day():
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))

    records, warnings = client.fetch_costs(
        DateRange(date(2026, 8, 1), date(2026, 8, 2)), today=date(2026, 8, 1)
    )

    assert records == []
    assert seen == [], "no cost_report request should be sent when no complete day is in range"
    assert len(warnings) == 1
    assert "no complete days" in warnings[0]


def test_anthropic_mtd_on_first_of_month_short_circuits():
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))
    first_of_month = date(2026, 8, 1)

    records, warnings = client.fetch_costs(range_for_period("mtd", first_of_month), today=first_of_month)

    assert records == []
    assert seen == []
    assert "no complete days" in warnings[0]


def test_anthropic_clamps_in_progress_day_off_the_range_end():
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))

    _, warnings = client.fetch_costs(DateRange(date(2026, 8, 1), date(2026, 8, 4)), today=date(2026, 8, 3))

    assert warnings == []
    assert seen[0]["starting_at"] == "2026-08-01T00:00:00Z"
    assert seen[0]["ending_at"] == "2026-08-03T00:00:00Z", "in-progress day should be dropped from the end"


def test_anthropic_leaves_fully_past_range_untouched():
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))

    _, warnings = client.fetch_costs(DateRange(date(2026, 8, 1), date(2026, 8, 3)), today=date(2026, 8, 18))

    assert warnings == []
    assert seen[0]["ending_at"] == "2026-08-03T00:00:00Z"


@pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "Pacific/Midway", "Asia/Tokyo", "America/New_York"])
def test_utc_today_ignores_local_timezone(monkeypatch, tz):
    """The clamp cutoff must track UTC, since Anthropic buckets are UTC-midnight aligned."""
    monkeypatch.setenv("TZ", tz)
    time.tzset()

    assert _utc_today() == datetime.now(timezone.utc).date()


def test_anthropic_clamp_default_cutoff_comes_from_utc_today(monkeypatch):
    """The default cutoff must come from _utc_today(), not the local date.

    Frozen rather than derived from the real clock: local and UTC dates only diverge for
    part of the day, so a wall-clock test would pass against the buggy code at some hours.
    """
    monkeypatch.setattr("llm_org_cost_monitor.providers._utc_today", lambda: date(2026, 8, 3))
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))

    client.fetch_costs(DateRange(date(2026, 8, 1), date(2026, 8, 20)))

    assert seen[0]["ending_at"] == "2026-08-03T00:00:00Z", "cutoff should follow _utc_today()"


def test_anthropic_clamp_default_short_circuits_on_utc_today(monkeypatch):
    monkeypatch.setattr("llm_org_cost_monitor.providers._utc_today", lambda: date(2026, 8, 1))
    seen = []
    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(_cost_report_handler(seen)))

    records, warnings = client.fetch_costs(DateRange(date(2026, 8, 1), date(2026, 8, 2)))

    assert records == []
    assert seen == []
    assert "no complete days" in warnings[0]


def test_anthropic_pagination_keeps_clamped_range_on_every_page():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations/workspaces":
            return httpx.Response(200, json={"data": [], "has_more": False})
        seen.append(dict(request.url.params))
        if len(seen) == 1:
            return httpx.Response(200, json={"data": [], "has_more": True, "next_page": "page_2"})
        return httpx.Response(200, json={"data": [], "has_more": False, "next_page": None})

    client = AnthropicCostClient("sk-ant-admin01-test", client=make_client(handler))
    client.fetch_costs(DateRange(date(2026, 8, 1), date(2026, 8, 4)), today=date(2026, 8, 3))

    assert len(seen) == 2, "expected a second page request"
    for page in seen:
        assert page["starting_at"] == "2026-08-01T00:00:00Z"
        assert page["ending_at"] == "2026-08-03T00:00:00Z"
