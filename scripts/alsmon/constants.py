"""Frozen identifiers and the explicit V1.1 monitoring query."""

from __future__ import annotations

SCRIPT_VERSION = "1.1.0"

BASELINE_ID = "2026-10-28"
BASELINE_TIMESTAMP = "2026-10-28T23:59:00-07:00"
BASELINE_FILENAME = "2026-10-28.json"

# The original static page recorded these two figures. They are historical
# context, not live totals. 1097 was the condition-search background count
# printed on the page; 486 is the length of the embedded DATA array.
HISTORICAL_BROAD_COUNT = 1097
HISTORICAL_EMBEDDED_COUNT = 486

API_URL = "https://clinicaltrials.gov/api/v2/studies"
SOURCE_NAME = "ClinicalTrials.gov API v2"
NCT_URL_PREFIX = "https://clinicaltrials.gov/study/"

# V1.1 monitoring query. This is deliberately explicit. It is close to, but
# not a silent continuation of, the 2026-10-28 static export: that page did
# not record the exact API query string. Diffs against the frozen baseline are
# scope reviews. Day-to-day change detection compares only successful snapshots
# produced by THIS query.
MONITORING_CONDITION = "ALS"
MONITORING_FILTER = (
    "AREA[InterventionType]DRUG OR AREA[InterventionType]BIOLOGICAL "
    "OR AREA[StudyType]EXPANDED_ACCESS"
)
PAGE_SIZE = 1000
MAX_PAGES = 50
PAGE_DELAY_SECONDS = 0.25
HTTP_TIMEOUT_SECONDS = 60
HTTP_RETRIES = 5
RETRY_STATUSES = (429, 500, 502, 503, 504)

# Below this previous size, a small absolute drop is not treated as an anomaly.
SHARP_DROP_MIN_PREVIOUS = 50
SHARP_DROP_RATIO = 0.7

# If more than this fraction of rows lack a posted update date, fail the run.
MAX_MISSING_UPDATE_DATE_FRACTION = 0.05

USER_AGENT = (
    "als-clinicaltrials-baseline/1.1 "
    "(public study metadata sync; +https://github.com/YoeyVol/als-clinicaltrials-baseline)"
)

STUDY_FIELDS = ",".join(
    [
        "NCTId",
        "BriefTitle",
        "OfficialTitle",
        "OverallStatus",
        "StudyType",
        "Phase",
        "Condition",
        "InterventionType",
        "InterventionName",
        "LeadSponsorName",
        "LocationFacility",
        "LocationCity",
        "LocationCountry",
        "LocationStatus",
        "LastUpdatePostDate",
        "StudyFirstPostDate",
        "LastUpdateSubmitDate",
        "StatusVerifiedDate",
        "HasResults",
        "ResultsFirstPostDate",
        "ResultsFirstSubmitDate",
        "OutcomeMeasureType",
        "OutcomeMeasureTitle",
        "OutcomeMeasureTimeFrame",
        "OutcomeMeasureParamType",
        "OutcomeMeasureUnitOfMeasure",
    ]
)

SCOPE_REVIEW_NOTE = (
    "Differences versus the frozen 2026-10-28 baseline are query-scope and "
    "time-window differences for human review. They are not a list of new trials "
    "and not cancellations. The original static page did not record the exact API "
    "query string. V1.1 monitoring uses query.cond=ALS plus a drug, biological, or "
    "expanded-access filter. Automatic change detection compares only the previous "
    "successful snapshot of this same query."
)

SCOPE_REVIEW_NOTE_ZH = (
    "与 2026-10-28 冻结基线的 NCT 差异，是查询口径和时间窗口不同，供人工复核。"
    "只出现在当前查询不是新增试验，只出现在历史基线也不是试验被取消。"
    "原始静态页没有保存当时的精确 API 查询字符串。"
    "V1.1 监测查询是 query.cond=ALS，并限定药物、生物制剂或扩展使用。"
    "自动变化检测只对照这一同一查询的上一次成功快照。"
)

LEFT_SCOPE_NOTE = (
    "This NCT was in the previous successful snapshot but is absent from the "
    "current query results. Do not describe this as cancelled, terminated, or "
    "withdrawn. Leaving the monitoring query is not evidence that the registration "
    "was cancelled."
)

LEFT_SCOPE_NOTE_ZH = (
    "该 NCT 出现在上一次成功快照中，但没有出现在本次查询结果里。"
    "这只表示它离开了当前检索范围，不是试验被取消、已终止或已撤回。"
)

SCHEMA_VERSION = 1
