from datetime import date
from decimal import Decimal

import httpx
import pytest

from llm_org_cost_monitor.dates import DateRange
from llm_org_cost_monitor.providers import AnthropicCostClient, OpenAICostClient, ProviderAPIError


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
