"""Small client for Yandex Metrika Reports API used by the Streamlit app."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import requests

TARGET_URL = "auth2.bitrix24.net/create"
API_ENDPOINT = "https://api-metrika.yandex.net/stat/v1/data"


class MetrikaConfigError(ValueError):
    """Raised when required Metrika configuration is missing."""


class MetrikaAPIError(RuntimeError):
    """Raised when Yandex Metrika API returns an error."""


@dataclass(frozen=True)
class MetrikaClient:
    token: str | None
    counter_id: str | int | None
    timeout: int = 30

    def __post_init__(self) -> None:
        if self.counter_id is not None:
            object.__setattr__(self, "counter_id", str(self.counter_id).strip())
        if self.token is not None:
            object.__setattr__(self, "token", str(self.token).strip())

    def _validate_config(self) -> None:
        if not self.token:
            raise MetrikaConfigError(
                "Не задан токен Яндекс Метрики. Добавьте YANDEX_METRIKA_TOKEN в .streamlit/secrets.toml или переменные окружения."
            )
        if not self.counter_id:
            raise MetrikaConfigError(
                "Не задан Counter ID. Добавьте YANDEX_METRIKA_COUNTER_ID или укажите счетчик в сайдбаре."
            )

    def fetch_report(
        self,
        metrics: str | Iterable[str],
        dimensions: str | Iterable[str] | None = None,
        date1: str | None = None,
        date2: str | None = None,
        filters: str | None = None,
        accuracy: str = "full",
        limit: int = 100000,
        sort: str | None = None,
        offset: int | None = None,
    ) -> pd.DataFrame:
        """Fetch a report and return a normalized DataFrame."""
        self._validate_config()
        metrics_str = _join(metrics)
        dimensions_str = _join(dimensions) if dimensions else None
        combined_filters = combine_filters(build_target_url_filter(), filters)

        params: dict[str, str | int] = {
            "id": self.counter_id or "",
            "date1": date1 or "7daysAgo",
            "date2": date2 or "today",
            "metrics": metrics_str,
            "filters": combined_filters,
            "accuracy": accuracy,
            "limit": limit,
        }
        if dimensions_str:
            params["dimensions"] = dimensions_str
        if sort:
            params["sort"] = sort
        if offset is not None:
            params["offset"] = offset

        headers = {"Authorization": f"OAuth {self.token}"}
        try:
            response = requests.get(API_ENDPOINT, headers=headers, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MetrikaAPIError(f"Не удалось выполнить запрос к API Метрики: {exc}") from exc

        if response.status_code in {401, 403}:
            raise MetrikaAPIError("API Метрики отклонил запрос: проверьте токен и доступ к счетчику.")
        if response.status_code >= 400:
            raise MetrikaAPIError(_extract_api_error(response))

        payload = response.json()
        return normalize_report(payload)


def _join(values: str | Iterable[str]) -> str:
    if isinstance(values, str):
        return values
    return ",".join(str(value) for value in values if str(value).strip())


def build_target_url_filter() -> str:
    """Central page filter. Uses contains to keep visits with query params."""
    return f"ym:pv:URL=@'{TARGET_URL}'"


def combine_filters(*filters: str | None) -> str:
    """Combine filters with AND and keep extension point in one place."""
    clean_filters = [flt.strip() for flt in filters if flt and flt.strip()]
    return " AND ".join(clean_filters)


def goal_reaches_metric(goal_id: str | int | None) -> str | None:
    goal_id = str(goal_id or "").strip()
    return f"ym:s:goal{goal_id}reaches" if goal_id else None


def goal_cr_metric(goal_id: str | int | None) -> str | None:
    goal_id = str(goal_id or "").strip()
    return f"ym:s:goal{goal_id}conversionRate" if goal_id else None


def normalize_report(payload: dict) -> pd.DataFrame:
    """Normalize /stat/v1/data response into dimension and metric columns."""
    rows = payload.get("data") or []
    query = payload.get("query") or {}
    metric_names = query.get("metrics") or []
    dimension_names = query.get("dimensions") or []

    normalized: list[dict] = []
    for row in rows:
        item: dict[str, object] = {}
        for index, dimension in enumerate(row.get("dimensions") or []):
            name = dimension_names[index] if index < len(dimension_names) else f"dimension_{index + 1}"
            item[name] = dimension.get("name") or dimension.get("id") or ""
        for index, value in enumerate(row.get("metrics") or []):
            name = metric_names[index] if index < len(metric_names) else f"metric_{index + 1}"
            item[name] = value
        normalized.append(item)

    return pd.DataFrame(normalized)


def _extract_api_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"API Метрики вернул ошибку {response.status_code}: {response.text[:500]}"
    message = payload.get("message") or payload.get("error") or str(payload)
    return f"API Метрики вернул ошибку {response.status_code}: {message}"
