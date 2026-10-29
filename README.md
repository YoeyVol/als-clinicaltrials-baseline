# ALS ClinicalTrials.gov 监测（V1.1）

这个仓库用 ClinicalTrials.gov API v2 的公开注册信息，跟踪渐冻症相关的药物、生物制剂和扩展使用研究。页面保留原来的布局、颜色和中文筛选。指标从 JSON 计算，不在页面里写死。

2026-10-28 的历史基线是冻结的：广义条件检索背景 **1097** 条，页面当时内嵌 **486** 条药物 / 生物制剂 / 扩展使用候选。这两项是历史记录，不是今天的事实。同步程序不会改写 `data/baselines/`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `data/baselines/2026-10-28.json` | 从旧 `index.html` 原样抽出的 486 条记录 |
| `data/baselines/2026-10-28.meta.json` | 来源、时间、范围、校验和、由记录算出的旧口径 |
| `data/latest/studies.json` | 当前监测查询的最近一次成功快照 |
| `data/latest/meta.json` | 源端时间、本站同步时间、查询参数、校验和、运行状态 |
| `data/latest/scope_vs_baseline.json` | 与冻结基线的 NCT 对照。这不是新增或取消清单 |
| `data/changes/` | 每次有跟踪字段变化时的报告 |
| `data/registry/first_seen.json` | NCT 首次进入本仓库成功快照的时间。没有联系人，没有患者信息 |
| `scripts/sync_clinicaltrials.py` | 本地同步 |
| `tests/fixtures/` | 离线 API 响应，测试不访问网络 |

## 监测查询

V1.1 的查询写在代码和每次成功快照的元数据里：

- `query.cond=ALS`
- `filter.advanced=AREA[InterventionType]DRUG OR AREA[InterventionType]BIOLOGICAL OR AREA[StudyType]EXPANDED_ACCESS`

`ALS` 条件检索会带上相关运动神经元病，例如肯尼迪病，偶尔也会返回疾病条件里既没有 ALS 也没有其他运动神经元病的记录。页面把这三类分开：严格 ALS、广义运动神经元病、其他条件。原始静态页没有保存当时的精确 API 字符串，所以这份查询不是对 2026-10-28 导出的静默延续。

和冻结基线比，只生成口径对照：两边都有、只在基线、只在当前查询。不要把差集写成新增试验，也不要把「只在基线」写成试验被取消。

自动变化检测只对照**同一查询的上一次成功快照**，识别：

- 新注册，或重新进入检索范围
- 离开检索范围（报告里写明这不是取消）
- 注册状态 `overallStatus`
- 分期
- 药物 / 生物制剂干预
- 地点（机构、城市、国家、地点状态）
- 结果发布，以及结果发布后的结果字段
- 研究类型 `studyType`（扩展使用以它为准，不靠状态名猜测）

`overallStatus` 和 `studyType` 分开保存。扩展使用只在 `studyType` 为 `EXPANDED_ACCESS` 时成立。地点联系人的姓名、邮箱和电话会被丢掉。

仅有 `lastUpdatePostDate` 变动、其他跟踪字段不变时，不会写新快照，也不会开 PR。页面上的「数据源更新时间」是上次写入的快照里最晚的 `lastUpdatePostDate`。

## 本地运行

```bash
python -m unittest discover -s tests -v
python scripts/sync_clinicaltrials.py --repo-root .
python -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/`。不要用 `file://` 直接打开 `index.html`，浏览器会拦截 JSON 请求。

只检查、不写文件：

```bash
python scripts/sync_clinicaltrials.py --dry-run
python scripts/sync_clinicaltrials.py --check
```

离线演示「新注册 / 状态变化 / 错误响应且不覆盖上次成功数据」：

```bash
python scripts/demo_scenarios.py
```

`--check` 和单元测试都不访问网络。

## 失败时怎么恢复

同步在写入之前检查分页是否完整、NCT 是否唯一、必填字段和时间格式，并拒绝空数据和相对上次成功快照的明显数量骤降（上次至少 50 条，且新结果少于 70%）。

出现 API 错误、分页不完整或上述异常时，程序以非 0 退出，**不修改** `data/latest`。上次成功的 `studies.json` 还在。

恢复步骤：

1. 看命令输出或 GitHub Actions 日志里的失败原因。
2. 不要删除 `data/latest`，也不要手工改 `data/baselines/2026-10-28.json`。
3. 网络或接口恢复后重新运行同步。
4. 如果 `data/latest/studies.json` 已经损坏，从 git 历史恢复这个文件，再重新同步。程序发现上次快照无法解析时会拒绝覆盖。

## 人工审核

GitHub Actions 在工作日定时运行，也可以手动 `workflow_dispatch`。有跟踪变化时，它把更新推到 `data-sync/日期` 分支并打开 Pull Request。没有变化时不提交。

审核 PR 时看 `data/changes/latest.json`：

- 每条变化有旧值、新值、NCT 官方链接、首见时间和检测时间。
- `left_query_scope` 表示离开当前查询，不能写成取消、终止或撤回。
- 与 2026-10-28 基线的差集在 `scope_vs_baseline.json`，标记为口径复核。
- 工作流权限只有 `contents: write` 和 `pull-requests: write`，用来推分支和开 PR。它不合并，不改 Pages 部署权限，也不使用密钥。

**不要自动合并。** 确认变化合理之后再人工合并。合并前，生产站点仍然是 `main` 上一次发布的内容。

## 页面口径

- 「正在招募」只统计 `RECRUITING`。
- 尚未招募、邀请入组、扩展使用、进行中（未招募）分开显示。
- 旧页面的「招募中类」把几种状态加在一起。页面会写出这个合并数，并说明它不是 N 个正在招募的试验。
- 分期柱可以重叠。一条试验有两个分期时会计入两次。
- 可以在「当前监测」和「2026-10-28 历史基线」之间切换。历史基线里的扩展使用是按状态推断的，因为当时的导出没有 `studyType`。
