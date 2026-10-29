# 罕见病 · ClinicalTrials.gov 试验基线

静态页：<https://yoeyvol.github.io/als-clinicaltrials-baseline/rare/>

## 口径

- 快照日期：**2026-10-29**（拉取时间 2026-10-29 11:33 PDT，时区 America/Los_Angeles）
- 来源：ClinicalTrials.gov API v2 `https://clinicaltrials.gov/api/v2/studies`
- 主查询：`query.term=("rare disease" OR orphan OR "orphan drug" OR "Office of Rare Diseases")`
- 入库：**1877** 条（API `totalCount` = 1877，`primaryTotalStored` = 1877）。`totalCount` 低于 3000，因此保留全部研究类型（干预、观察、扩展可及），没有退化为仅药物试验。
- 这是 ClinicalTrials.gov 上的 **关键词 / orphan 检索**，不是 Orphanet 意义上「每一种罕见病」的完整普查。具体病种试验（例如 ALS）若标题或条件里不写 “rare disease”，不会全部进入本库。ALS 基线在本仓库根目录，与本目录互不影响。

对照计数（未作为本库入库条件）：`query.cond=rare disease` 1041；`query.term="rare disease"` 1364；`query.term=orphan OR "orphan drug"` 532。

## 文件

| 路径 | 内容 |
| --- | --- |
| `index.html` | 中文可检索页面（1877 条内嵌，不依赖外部数据文件即可打开） |
| `data/latest.json` | `meta` + `studies`（1877） |
| `data/Rare_ClinicalTrials_baseline_2026-10-29.csv` | 同口径表格导出（含表头 1878 行） |
| `data/Rare_ClinicalTrials_baseline_2026-10-29.jsonl` | 同口径 JSONL（1877 行） |
