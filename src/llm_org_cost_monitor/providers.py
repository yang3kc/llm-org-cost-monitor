from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .dates import DateRange
from .models import CostRecord, ProviderStatus

USER_AGENT = "llm-org-cost-monitor/0.1.0"


class ProviderAPIError(RuntimeError):
    def __init__(self, provider: str, status_code: int, message: str):
        super().__init__(f"{provider} API error {status_code}: {message}")
        self.provider = provider
        self.status_code = status_code
        self.message = message


class MissingKeyError(RuntimeError):
    pass


class OpenAICostClient:
    base_url = "https://api.openai.com/v1"

    def __init__(self, admin_key: str | None, label: str = "OpenAI", client: httpx.Client | None = None):
        if not admin_key:
            raise MissingKeyError("OPENAI_ADMIN_KEY is not set")
        self.label = label
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {admin_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    def fetch_costs(self, date_range: DateRange) -> tuple[list[CostRecord], list[str]]:
        warnings: list[str] = []
        project_names = self._safe_project_names(warnings)
        records: list[CostRecord] = []
        params: list[tuple[str, Any]] = [
            ("start_time", date_range.openai_start_seconds()),
            ("end_time", date_range.openai_end_seconds()),
            ("bucket_width", "1d"),
            ("limit", 180),
            ("group_by", "project_id"),
            ("group_by", "line_item"),
        ]

        for page in self._pages("/organization/costs", params):
            for bucket in page.get("data", []):
                bucket_date = _date_from_unix(bucket.get("start_time"))
                for result in bucket.get("results", []):
                    amount_obj = result.get("amount") or {}
                    amount = _decimal_from_value(amount_obj.get("value"))
                    currency = str(amount_obj.get("currency") or "usd").upper()
                    project_id = result.get("project_id")
                    records.append(
                        CostRecord(
                            provider="openai",
                            account_label=self.label,
                            date=bucket_date,
                            amount=amount,
                            currency=currency,
                            project_id=project_id,
                            project_name=project_names.get(project_id) if project_id else None,
                            line_item=result.get("line_item"),
                            raw_amount=amount_obj,
                        )
                    )
        return records, warnings

    def doctor(self) -> ProviderStatus:
        projects = self.list_project_names()
        return ProviderStatus(
            provider="openai",
            label=self.label,
            status="ok",
            metadata=f"{len(projects)} projects visible",
        )

    def _safe_project_names(self, warnings: list[str]) -> dict[str, str]:
        try:
            return self.list_project_names()
        except ProviderAPIError as exc:
            warnings.append(f"OpenAI project name mapping failed: {exc.message}")
            return {}

    def list_project_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        params: list[tuple[str, Any]] = [("limit", 100)]
        for page in self._pages("/organization/projects", params):
            for item in page.get("data", []):
                project_id = item.get("id")
                if project_id:
                    names[project_id] = item.get("name") or project_id
        return names

    def _pages(self, path: str, base_params: list[tuple[str, Any]]):
        next_page: str | None = None
        seen_pages = 0
        while True:
            params = list(base_params)
            if next_page:
                params.append(("page", next_page))
            response = self._client.get(f"{self.base_url}{path}", headers=self._headers, params=params)
            data = _checked_json("openai", response)
            yield data
            seen_pages += 1
            next_page = data.get("next_page")
            if not data.get("has_more") or not next_page:
                break
            if seen_pages >= 100:
                raise ProviderAPIError("openai", 599, "pagination exceeded 100 pages")


class AnthropicCostClient:
    base_url = "https://api.anthropic.com/v1"

    def __init__(self, admin_key: str | None, label: str = "Anthropic", client: httpx.Client | None = None):
        if not admin_key:
            raise MissingKeyError("ANTHROPIC_ADMIN_KEY is not set")
        self.label = label
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "anthropic-version": "2023-06-01",
            "x-api-key": admin_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    def fetch_costs(self, date_range: DateRange) -> tuple[list[CostRecord], list[str]]:
        warnings: list[str] = []
        workspace_names = self._safe_workspace_names(warnings)
        records: list[CostRecord] = []
        params: list[tuple[str, Any]] = [
            ("starting_at", date_range.anthropic_start()),
            ("ending_at", date_range.anthropic_end()),
            ("bucket_width", "1d"),
            ("limit", 31),
            ("group_by[]", "workspace_id"),
            ("group_by[]", "description"),
        ]

        for page in self._pages("/organizations/cost_report", params):
            for bucket in page.get("data", []):
                bucket_date = _date_from_rfc3339(bucket.get("starting_at"))
                for result in bucket.get("results", []):
                    raw_amount = result.get("amount", 0)
                    workspace_id = result.get("workspace_id")
                    records.append(
                        CostRecord(
                            provider="anthropic",
                            account_label=self.label,
                            date=bucket_date,
                            amount=_anthropic_amount_to_usd(raw_amount),
                            currency=str(result.get("currency") or "USD").upper(),
                            workspace_id=workspace_id,
                            workspace_name=workspace_names.get(workspace_id) if workspace_id else None,
                            line_item=result.get("description"),
                            raw_amount=raw_amount,
                        )
                    )
        return records, warnings

    def doctor(self) -> ProviderStatus:
        workspaces = self.list_workspace_names()
        return ProviderStatus(
            provider="anthropic",
            label=self.label,
            status="ok",
            metadata=f"{len(workspaces)} workspaces visible",
        )

    def _safe_workspace_names(self, warnings: list[str]) -> dict[str | None, str]:
        try:
            return self.list_workspace_names()
        except ProviderAPIError as exc:
            warnings.append(f"Anthropic workspace name mapping failed: {exc.message}")
            return {}

    def list_workspace_names(self) -> dict[str | None, str]:
        names: dict[str | None, str] = {}
        params: list[tuple[str, Any]] = [("limit", 100)]
        for page in self._pages("/organizations/workspaces", params):
            for item in page.get("data", []):
                workspace_id = item.get("id")
                if workspace_id:
                    names[workspace_id] = item.get("name") or workspace_id
        return names

    def _pages(self, path: str, base_params: list[tuple[str, Any]]):
        next_page: str | None = None
        seen_pages = 0
        while True:
            params = list(base_params)
            if next_page:
                params.append(("page", next_page))
            response = self._client.get(f"{self.base_url}{path}", headers=self._headers, params=params)
            data = _checked_json("anthropic", response)
            yield data
            seen_pages += 1
            next_page = data.get("next_page")
            if not data.get("has_more") or not next_page:
                break
            if seen_pages >= 100:
                raise ProviderAPIError("anthropic", 599, "pagination exceeded 100 pages")


def _checked_json(provider: str, response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = _safe_error_detail(response)
        raise ProviderAPIError(provider, response.status_code, detail)
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderAPIError(provider, response.status_code, "response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise ProviderAPIError(provider, response.status_code, "response JSON was not an object")
    return data


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict):
                return str(error.get("message") or error.get("type") or error)[:300]
            return str(error)[:300]
    except ValueError:
        pass
    return response.text[:300] or response.reason_phrase


def _decimal_from_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProviderAPIError("provider", 422, f"invalid amount value {value!r}") from exc


def _anthropic_amount_to_usd(value: Any) -> Decimal:
    return (_decimal_from_value(value) / Decimal("100")).quantize(Decimal("0.000001"))


def _date_from_unix(value: Any):
    if value is None:
        raise ProviderAPIError("openai", 422, "bucket missing start_time")
    return datetime.fromtimestamp(int(value), tz=timezone.utc).date()


def _date_from_rfc3339(value: Any):
    if not value:
        raise ProviderAPIError("anthropic", 422, "bucket missing starting_at")
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).date()
