from __future__ import annotations

import os
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st

from metrika_client import (
    MetrikaAPIError,
    MetrikaClient,
    MetrikaConfigError,
    TARGET_URL,
    goal_cr_metric,
    goal_reaches_metric,
)

VISITS = "ym:s:visits"
USERS = "ym:s:users"
BOUNCE_RATE = "ym:s:bounceRate"
PAGE_DEPTH = "ym:s:pageDepth"
AVG_DURATION = "ym:s:avgVisitDurationSeconds"

OPTIONAL_GOALS = {
    "start": ("Начал регистрацию", "YANDEX_METRIKA_START_GOAL_ID"),
    "form": ("Отправил форму / следующий шаг", "YANDEX_METRIKA_FORM_GOAL_ID"),
    "next": ("Дошел до следующего шага", "YANDEX_METRIKA_NEXT_STEP_GOAL_ID"),
    "error": ("Ошибка регистрации", "YANDEX_METRIKA_ERROR_GOAL_ID"),
}


def read_setting(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default) or "").strip()


def make_metrics(reg_goal_id: str | None) -> list[str]:
    metrics = [VISITS, USERS, BOUNCE_RATE, PAGE_DEPTH, AVG_DURATION]
    if reg_goal_id:
        metrics.extend([goal_reaches_metric(reg_goal_id), goal_cr_metric(reg_goal_id)])
    return [metric for metric in metrics if metric]


def registrations_column(reg_goal_id: str | None) -> str | None:
    return goal_reaches_metric(reg_goal_id)


def cr_column(reg_goal_id: str | None) -> str | None:
    return goal_cr_metric(reg_goal_id)


def safe_number(df: pd.DataFrame, column: str | None, default: float = 0.0) -> float:
    if df.empty or not column or column not in df.columns:
        return default
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).iloc[0])


def fmt_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def fmt_duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.1f} мин"
    return f"{seconds:.0f} сек"


def prepare_report(df: pd.DataFrame, reg_goal_id: str | None) -> pd.DataFrame:
    df = df.copy()
    reg_col = registrations_column(reg_goal_id)
    cr_col = cr_column(reg_goal_id)
    rename_map = {
        VISITS: "visits",
        USERS: "users",
        BOUNCE_RATE: "bounceRate",
        PAGE_DEPTH: "pageDepth",
        AVG_DURATION: "avgDurationSeconds",
    }
    if reg_col:
        rename_map[reg_col] = "registrations"
    if cr_col:
        rename_map[cr_col] = "CR"
    df = df.rename(columns=rename_map)
    for column in ["visits", "users", "bounceRate", "pageDepth", "avgDurationSeconds", "registrations", "CR"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    if "registrations" not in df.columns:
        df["registrations"] = 0
    if "CR" not in df.columns and "visits" in df.columns:
        df["CR"] = df.apply(lambda row: row["registrations"] / row["visits"] * 100 if row["visits"] else 0, axis=1)
    return df


@st.cache_data(show_spinner=False)
def cached_fetch(
    token: str,
    counter_id: str,
    metrics: tuple[str, ...],
    dimensions: tuple[str, ...],
    date1: str,
    date2: str,
    refresh_key: int,
    accuracy: str,
    limit: int,
    sort: str | None,
) -> pd.DataFrame:
    client = MetrikaClient(token=token, counter_id=counter_id)
    return client.fetch_report(
        metrics=list(metrics),
        dimensions=list(dimensions) or None,
        date1=date1,
        date2=date2,
        accuracy=accuracy,
        limit=limit,
        sort=sort,
    )


def load_report(
    token: str,
    counter_id: str,
    metrics: list[str],
    dimensions: list[str],
    date1: str,
    date2: str,
    refresh_key: int,
    accuracy: str = "high",
    limit: int = 100000,
    sort: str | None = None,
) -> pd.DataFrame:
    return cached_fetch(token, counter_id, tuple(metrics), tuple(dimensions), date1, date2, refresh_key, accuracy, limit, sort)


def is_too_complicated(exc: MetrikaAPIError) -> bool:
    return "query is too complicated" in str(exc).lower()


def lighter_accuracies(accuracy: str) -> list[str]:
    order = ["full", "high", "medium", "low"]
    normalized = (accuracy or "high").lower()
    if normalized not in order:
        normalized = "high"
    return order[order.index(normalized) :]


def safe_load_report(
    title: str,
    token: str,
    counter_id: str,
    metrics: list[str],
    dimensions: list[str],
    date1: str,
    date2: str,
    refresh_key: int,
    accuracy: str = "high",
    limit: int = 1000,
    sort: str | None = None,
) -> pd.DataFrame:
    last_error: MetrikaAPIError | None = None
    for attempt_accuracy in lighter_accuracies(accuracy):
        try:
            return load_report(token, counter_id, metrics, dimensions, date1, date2, refresh_key, attempt_accuracy, limit, sort)
        except MetrikaAPIError as exc:
            last_error = exc
            if not is_too_complicated(exc):
                break
    if last_error:
        st.warning(
            f"{title}: Метрика не смогла построить этот отчет на выбранном периоде с текущей точностью. "
            "Попробуйте уменьшить период или выбрать более быстрый режим точности. "
            f"Текст ошибки: {last_error}"
        )
    return pd.DataFrame()


def date_range_from_sidebar() -> tuple[str, str]:
    period = st.sidebar.selectbox("Период", ["Последние 7 дней", "Последние 14 дней", "Последние 30 дней", "Произвольный период"], index=2)
    today = date.today()
    if period == "Произвольный период":
        start, end = st.sidebar.date_input("Даты", value=(today - timedelta(days=30), today), max_value=today)
    else:
        days = int(period.split()[1])
        start, end = today - timedelta(days=days - 1), today
    return start.isoformat(), end.isoformat()


def show_empty_if_needed(df: pd.DataFrame) -> bool:
    if df.empty:
        st.info("Метрика вернула пустой результат для страницы регистрации и выбранного периода.")
        return True
    return False


def styled_problem_rows(df: pd.DataFrame, avg_cr: float, avg_bounce: float):
    def highlight(row):
        is_problem = row.get("visits", 0) > 100 and (row.get("CR", 0) < avg_cr * 0.8 or row.get("bounceRate", 0) > avg_bounce)
        return ["background-color: #fff3cd" if is_problem else "" for _ in row]
    return df.style.apply(highlight, axis=1).format({"CR": "{:.1f}%", "bounceRate": "{:.1f}%", "lost_registrations": "{:.1f}"})


def dimension_table(title: str, df: pd.DataFrame, dimension: str, avg_cr: float, avg_bounce: float) -> None:
    st.subheader(title)
    if show_empty_if_needed(df):
        return
    dimension_name = dimension.split(":")[-1]
    df = prepare_report(df, st.session_state.reg_goal_id).rename(columns={dimension: dimension_name})
    cols = [dimension_name, "visits", "registrations", "CR", "bounceRate"]
    st.dataframe(styled_problem_rows(df[cols].sort_values("visits", ascending=False), avg_cr, avg_bounce), use_container_width=True)


def add_losses(df: pd.DataFrame, avg_cr_fraction: float) -> pd.DataFrame:
    df = df.copy()
    df["expected_registrations"] = df["visits"] * avg_cr_fraction
    df["lost_registrations"] = (df["expected_registrations"] - df["registrations"]).clip(lower=0)
    return df[df["lost_registrations"] > 0]


def main() -> None:
    st.set_page_config(page_title="Аналитика регистрации / Network", layout="wide")
    st.session_state.setdefault("refresh_key", 0)

    token = read_setting("YANDEX_METRIKA_TOKEN")
    default_counter = read_setting("YANDEX_METRIKA_COUNTER_ID")
    default_reg_goal = read_setting("YANDEX_METRIKA_REG_GOAL_ID")
    date1, date2 = date_range_from_sidebar()
    accuracy_label = st.sidebar.selectbox("Точность данных", ["Быстрее", "Точнее", "Максимально точно"], index=1)
    report_accuracy = {"Быстрее": "medium", "Точнее": "high", "Максимально точно": "full"}[accuracy_label]
    counter_id = st.sidebar.text_input("Counter ID", value=default_counter).strip()
    reg_goal_id = st.sidebar.text_input("Goal ID успешной регистрации", value=default_reg_goal).strip()
    st.session_state.reg_goal_id = reg_goal_id
    optional_goal_ids = {key: st.sidebar.text_input(label, value=read_setting(env)).strip() for key, (label, env) in OPTIONAL_GOALS.items()}
    if st.sidebar.button("Обновить данные"):
        st.session_state.refresh_key += 1
        st.cache_data.clear()

    st.title("Аналитика страницы регистрации / Network")
    st.caption(f"{TARGET_URL}/")
    st.info("Все отчеты автоматически фильтруются по визитам, где URL содержит auth2.bitrix24.net/create.")

    if not token:
        st.warning("Добавьте YANDEX_METRIKA_TOKEN в .streamlit/secrets.toml или переменные окружения. Токен не выводится в интерфейс.")
        return
    if not counter_id:
        st.warning("Укажите Counter ID в сайдбаре или настройте YANDEX_METRIKA_COUNTER_ID.")
        return
    if not reg_goal_id:
        st.warning("Goal ID успешной регистрации не указан: CR и регистрации будут недоступны или равны 0.")

    metrics = make_metrics(reg_goal_id)
    try:
        total_raw = load_report(token, counter_id, metrics, [], date1, date2, st.session_state.refresh_key, accuracy="full")
    except (MetrikaConfigError, MetrikaAPIError) as exc:
        st.error(str(exc))
        return
    if show_empty_if_needed(total_raw):
        return
    total = prepare_report(total_raw, reg_goal_id)
    visits = safe_number(total, "visits")
    users = safe_number(total, "users")
    regs = safe_number(total, "registrations")
    avg_cr = regs / visits * 100 if visits else 0
    avg_bounce = safe_number(total, "bounceRate")

    kpis = st.columns(7)
    kpis[0].metric("Визиты", fmt_int(visits), help="Визиты на страницу регистрации.")
    kpis[1].metric("Пользователи", fmt_int(users))
    kpis[2].metric("Успешные регистрации", fmt_int(regs))
    kpis[3].metric("CR в регистрацию", fmt_pct(avg_cr), help="Доля визитов, завершившихся успешной регистрацией.")
    kpis[4].metric("Отказы", fmt_pct(avg_bounce), help="Bounce Rate по данным Метрики.")
    kpis[5].metric("Длительность", fmt_duration(safe_number(total, "avgDurationSeconds")))
    kpis[6].metric("Глубина", f"{safe_number(total, 'pageDepth'):.2f}")

    tab_dyn, tab_dev, tab_src, tab_funnel, tab_problems = st.tabs(["Динамика", "Устройства", "Источники", "Промежуточные цели", "Проблемные сегменты"])

    with tab_dyn:
        df = prepare_report(
            safe_load_report("Динамика", token, counter_id, metrics, ["ym:s:date"], date1, date2, st.session_state.refresh_key, report_accuracy, limit=10000),
            reg_goal_id,
        ).rename(columns={"ym:s:date": "date"})
        if not show_empty_if_needed(df):
            st.dataframe(df[["date", "visits", "users", "registrations", "CR", "bounceRate"]].style.format({"CR": "{:.1f}%", "bounceRate": "{:.1f}%"}), use_container_width=True)
            st.plotly_chart(px.line(df, x="date", y=["visits", "registrations"], markers=True), use_container_width=True)

    with tab_dev:
        for title, dim in [("Категория устройства", "ym:s:deviceCategory"), ("Браузер", "ym:s:browser"), ("Операционная система", "ym:s:operatingSystem")]:
            dimension_table(
                title,
                safe_load_report(title, token, counter_id, metrics, [dim], date1, date2, st.session_state.refresh_key, report_accuracy, limit=1000, sort=f"-{VISITS}"),
                dim,
                avg_cr,
                avg_bounce,
            )

    with tab_src:
        source_reports = [
            ("Источник трафика", "ym:s:lastTrafficSource", 1000),
            ("UTM Source", "ym:s:UTMSource", 1000),
            ("UTM Medium", "ym:s:UTMMedium", 1000),
            ("UTM Campaign", "ym:s:UTMCampaign", 1000),
            ("UTM Content", "ym:s:UTMContent", 500),
        ]
        st.caption("lost_registrations — потенциальные потери относительно среднего CR страницы.")
        for title, dim, limit in source_reports:
            raw_df = safe_load_report(title, token, counter_id, metrics, [dim], date1, date2, st.session_state.refresh_key, report_accuracy, limit=limit, sort=f"-{VISITS}")
            if raw_df.empty:
                continue
            df = prepare_report(raw_df, reg_goal_id).rename(columns={dim: "segment"})
            df = add_losses(df, avg_cr / 100)
            cols = ["segment", "visits", "registrations", "CR", "bounceRate", "lost_registrations"]
            st.subheader(title)
            st.dataframe(
                df[cols].sort_values(["lost_registrations", "visits"], ascending=False).style.format({"CR": "{:.1f}%", "bounceRate": "{:.1f}%", "lost_registrations": "{:.1f}"}),
                use_container_width=True,
            )

    with tab_funnel:
        goal_steps = [("Визиты на create", None)]
        goal_steps.extend((label, optional_goal_ids[key]) for key, (label, _env) in OPTIONAL_GOALS.items() if optional_goal_ids.get(key))
        if reg_goal_id:
            goal_steps.append(("Успешная регистрация", reg_goal_id))
        if len(goal_steps) == 1 or (len(goal_steps) == 2 and reg_goal_id):
            st.info("Промежуточные цели не заданы. Сейчас считаем только визиты и успешные регистрации.")
        funnel_rows = []
        previous = None
        for label, gid in goal_steps:
            reaches = visits if gid is None else safe_number(prepare_report(load_report(token, counter_id, [goal_reaches_metric(gid)], [], date1, date2, st.session_state.refresh_key, accuracy="full"), gid), "registrations")
            funnel_rows.append({"step": label, "reaches": reaches, "conversion_from_visits": reaches / visits * 100 if visits else 0, "drop_off_from_previous": (previous - reaches) / previous * 100 if previous else 0})
            previous = reaches
        st.dataframe(pd.DataFrame(funnel_rows).style.format({"reaches": "{:.0f}", "conversion_from_visits": "{:.1f}%", "drop_off_from_previous": "{:.1f}%"}), use_container_width=True)

    with tab_problems:
        segments = [("deviceCategory", "ym:s:deviceCategory"), ("browser", "ym:s:browser"), ("operatingSystem", "ym:s:operatingSystem"), ("UTM Campaign", "ym:s:UTMCampaign"), ("traffic source", "ym:s:lastTrafficSource")]
        frames = []
        for label, dim in segments:
            raw_sdf = safe_load_report(label, token, counter_id, metrics, [dim], date1, date2, st.session_state.refresh_key, report_accuracy, limit=1000, sort=f"-{VISITS}")
            if raw_sdf.empty:
                continue
            sdf = prepare_report(raw_sdf, reg_goal_id).rename(columns={dim: "segment"})
            if not sdf.empty:
                sdf["segment_type"] = label
                frames.append(sdf)
        if frames:
            problems = pd.concat(frames, ignore_index=True)
            problems["average_CR"] = avg_cr
            problems["CR_delta"] = problems["CR"] - avg_cr
            problems = add_losses(problems, avg_cr / 100)
            problems = problems[problems["CR"] < avg_cr]
            def priority(row):
                if row["visits"] >= 300 and row["CR"] <= avg_cr * 0.7:
                    return "High"
                if row["visits"] >= 100 and row["CR"] <= avg_cr * 0.8:
                    return "Medium"
                return "Low"
            problems["priority"] = problems.apply(priority, axis=1)
            cols = ["segment_type", "segment", "visits", "registrations", "CR", "average_CR", "CR_delta", "lost_registrations", "priority"]
            st.dataframe(problems[cols].sort_values("lost_registrations", ascending=False).style.format({"CR": "{:.1f}%", "average_CR": "{:.1f}%", "CR_delta": "{:.1f}%", "lost_registrations": "{:.1f}"}), use_container_width=True)
        else:
            st.info("Недостаточно данных для поиска проблемных сегментов.")


if __name__ == "__main__":
    main()
