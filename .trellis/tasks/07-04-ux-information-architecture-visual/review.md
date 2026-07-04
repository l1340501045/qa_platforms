# 阶段 D 自审报告：信息架构与视觉骨架

## 本轮完成

- 将产品口径明确为“具备 QA 背景、但首次使用本平台的人”。
- 主导航从对象管理导向改为工作流导向：
  - 工作台 `/review`
  - 项目/系统 `/systems`
  - 用例资产 `/case-library`
  - 全局搜索 `/search`
  - 导出中心 `/exports`
- `/` 默认进入工作台，旧路由仍保留。
- 新增轻量共享 UI 骨架：
  - `PageShell`
  - `PageHeader`
  - `FilterBar`
  - `MetricStrip`
  - `SplitPane`
  - `EmptyState`
  - `StatusTag`
  - `layoutTokens`
- 接入页面：
  - 系统列表。
  - 知识库。
  - 工作台/审核中心。
  - 批次工作台。
  - 用例资产。
  - 全局搜索。
  - 导出中心。
- 工作台默认从“待审核”改为“全部批次”，并补充排队中、生成中、待澄清、失败等筛选，避免首次进入看不到真正需要处理的批次。

## 批判性 Review

### 1. 是否更符合专业 QA 首次使用的动线

结论：有明显改善，但还不是最终态。

改善点：

- 导航文案从“系统管理/审核中心/用例库”变成“工作台/项目/系统/用例资产/全局搜索/导出中心”，更贴近 QA 日常任务流。
- 页面头统一解释当前页面负责什么，首次使用者不用通过猜菜单理解入口关系。
- 系统列表、知识库、工作台、用例资产、导出中心都出现了统计摘要和下一步语义。
- 工作台现在默认可看到所有批次状态，符合“先处理待澄清/失败/待审”的工作方式。

本轮补充后的改善点：

- 工作台已经有待澄清、失败、生成中、待审核四个分组待办面板。
- 分组待办只使用现有 `GET /batches?status=...` 能力，不改后端生成契约。
- 队列“筛选”按钮会驱动下方完整批次表格，既能快速定位，也保留完整浏览。
- 工作台待办区新增处理顺序和排序说明：待澄清 -> 失败 -> 待审核 -> 生成中；队列按后端 `created_at desc` 展示。每个队列默认露出最近 3 条，可展开到最近 8 条，并提供“查看全部 N 条”驱动下方分页表格。
- 批次动作文案按状态区分：待澄清是“处理澄清”，失败是“查看失败”，生成中是“查看进度”，待审核是“去审核”。
- 知识库页补齐“上传资料 -> 生成批次 -> 进入审查”的三步提示。
- 文档列表新增“生成用例 / 查看详情”操作列，生成复用现有 `triggerGeneration(documentId)`，成功后进入批次工作台。
- 知识库上传区把“资料类型”前置为上传前决策，拖拽区和文件夹上传按钮都会显示本次入库类型，避免上传后才发现类型错误。
- 选择“其他”类型时增加风险提示和上传确认，避免 PRD、技术文档或测试规则误入 `other` 后影响自动关联与生成依据。
- 文档列表将“生成用例 / 查看详情”并入标题主列，1024 宽度下主流程动作仍可见，不再藏在表格横向滚动深处。
- 补齐全局布局 reset，消除浏览器默认 body margin 导致的弹窗后 8px 横向滚动；知识库文档表格改为表格内横向滚动，不撑开页面。
- 文档详情页从旧式 Card/Descriptions 改为 PageShell/PageHeader/MetricStrip 骨架。
- 文档详情顶部直接暴露文档类型、导入状态、嵌入状态、直接/间接关联数，并保留生成、解析详情、知识速查表入口。
- 文档详情生成动作改为确认弹窗，复用现有 `triggerGeneration(documentId)`，成功后进入批次工作台。
- 从知识库列表或文档详情触发生成进入批次页时，URL 会保留 `from=knowledge` 或 `from=document` 上下文；批次页显示“返回知识库 / 返回文档详情”，便于 QA 回头补资料、看解析或关联文档。
- 从知识库进入文档详情时，详情 URL 带 `from=knowledge&system_id=...`；文档详情顶部显示“返回知识库”，刷新后仍能回到原系统知识库。
- 修复文档详情真实白屏：前端原本按 `{direct, indirect}` 读取关联接口，但后端真实返回分页 `{items,total,page...}`，加载关联后会运行时崩溃；现在在前端服务层做响应归一化，空关联不会切断详情页和生成前检查通路。
- 修复添加文档关联请求字段映射：前端 UI 仍使用 `target_document_id`，提交给后端时转换为 `source_doc_id + target_doc_id + relation_type`，不改变后端契约。
- 关联文档区域改成追溯语义，空列表给出“先关联技术文档、原型或测试规则”的恢复提示。
- 批次工作台 `/batches/:batchId` 补齐执行面结构：顶部状态指标、状态下一步提示、阶段进度、用例审查说明、树表工作区、底部审查动作。
- 批次状态摘要现在直接暴露批次状态、阶段进度、用例总数、待审、需修改、待澄清，首次进入不需要先理解所有控件才知道当前批次卡在哪里。
- 待澄清/失败/待审等状态的顶部动作按状态变化，保留重新入队、处理澄清、触发迭代、落库归档等主流程入口。
- 批次审查树表改为共享 `SplitPane` 工作区；1024 宽度下自动上下堆叠，避免右侧表格过窄导致操作列藏得太深。
- 用例表格压缩固定列宽并使用局部 `scroll.x`，1024 宽度下确认、需修改、删除等核心行内操作可见，且不产生页面级横向溢出。
- 修掉批次页加载态的 Ant Design v5 `Spin tip` 控制台警告。
- 系统列表 `/systems` 从卡片墙改为更适合扫描的表格入口。
- 系统列表增加当前页筛选和排序：系统名称/描述筛选、资料状态筛选、最近活动/名称/文档数/批次数排序；不改后端搜索契约，明确只作用于当前页。
- 系统列表状态从文档数/批次数派生为“待上传资料 / 已有资料 / 已有批次”，并把“上传资料 / 发起生成 / 进入知识库”放进系统主列，1024 宽度下也可见。
- 编辑/删除管理动作也进入系统主列，保留删除确认弹窗，避免窄屏下被表格横向滚动藏住。
- 系统列表加载失败时不再落入“还没有项目/系统”空态；页面显示“系统列表加载失败”“重试加载”，指标条显示 `- / 加载失败`，避免把接口失败误判成真实无数据或假 0。
- 系统列表成功返回但缺少文档数/批次数字段时，状态显示为“统计不可用”，数量显示 `--`，指标条提示“统计字段缺失”；不再把缺失字段派生成“待上传资料”或假 0。
- Playwright 运行态巡检发现全局顶栏标题在 1024 宽截图中被裁切；根因是 Ant Design `Layout.Header` 默认 `line-height: 64px` 被副标题继承。已在 `MainLayout` 顶栏文本容器重置行高，恢复页面方位标题的首屏可读性。
- 用例资产 `/case-library` 从纯树表浏览改为 QA 资产工作台。
- 用例资产顶部明确“主集候选 / 全部资产 / 待处理资产”三种视图，默认主集候选，避免首次进入时误以为这里是待审核列表。
- Playwright 与真实接口取证显示 `view=stable` 在漫剧系统返回 1852 条 `bucket=main` 且 `review_status=pending` 的用例；因此页面文案从“稳定主集/可复用资产”校准为“主集候选”，避免 QA 误以为待审用例已经可复用。
- 主集候选如果仍含待审或需修改用例，页面会显式提示“主集候选仍有待处理用例”，并提供“查看待处理资产”和“去工作台审查”两个动作；不再只把债务藏在指标条数字里。
- 用例资产保留当前系统的“上传/生成”入口，确保从资产沉淀页能回到完整生成链路，不形成主流程死路。
- 用例资产默认系统不再按 `/systems/options` 的名称排序选第一个空系统；现在会用 `/systems` 的文档数/批次数作为增强信号，首次进入优先落到有批次/文档的系统。若统计增强失败，仍回退到原系统选项，不阻塞页面。
- 用例资产筛选条按“系统 -> 资产视图 -> 批次范围 -> 质量筛选”重排，控件保留标签，不只依赖 placeholder。
- 用例资产指标条新增当前视图用例、选中范围、分支节点、待处理、重复标记等资产判断信息。
- 左侧树保留搜索、展开全部、收起全部，但容器固定为局部滚动；默认不展开所有分支，降低大模块树下滚动找目录的成本。
- 右侧表格显示选中范围、范围类型、批次范围和资产视图标签；空态提供重置筛选或去知识库上传/生成的恢复路径。
- 用例资产树节点增加单行省略和完整 `title`，长文档名/模块名不会挤掉数量标签，也不会撑开页面。
- 用例资产表格标题限制为 2 行并保留完整 `title`/详情抽屉通路，避免 20 条分页因为超长标题变成多屏滚动墙。
- 用例资产批次范围说明从“默认最新可见批次”校准为“默认：各文档最新可见批次”，并说明可见状态是待审阅/已完成/已落库；下拉显示当前可选批次数，列表失败时禁用并标记 warning，避免把批次接口失败误判成没有历史批次。
- 导出中心 `/exports` 从导出任务表改为“用例交付导出”工作台。
- 导出中心顶部说明 Markdown / Excel 的交付场景，并新增刷新、状态筛选、可下载文件指标。
- 导出任务主列直接展示范围、格式、短 ID、创建时间、下载入口和失败恢复提示，1024 宽度下下载动作可见。
- 新建导出弹窗不再把系统/批次选项加载失败伪装成空下拉；系统列表失败、批次列表失败都会显示 warning 和重试动作，批次导出只展示待审阅/已完成/已落库的可交付批次。
- 新建导出弹窗补充批次导出/系统导出的区别，以及 Markdown / Excel 格式说明；创建请求仍复用现有 `POST /exports` 契约。
- 全局搜索 `/search` 不再在初始进入时显示空表格，改为说明性空态，明确可搜索业务功能、断言关键词或边界条件。
- 搜索页筛选控件补齐“系统 / 优先级 / 审核状态”可见标签，避免只靠 placeholder 解释筛选语义。
- 搜索结果标题主列补充“定位到批次 / 来源文档”追溯动作；搜到结果后能直接回到来源批次或来源资料继续审查。
- 从全局搜索进入批次或来源文档时，URL 会保留 `from=search` 和当前关键词/系统/优先级/审核状态/分页；批次页和文档详情页显示“返回搜索结果”，刷新后仍能回到原搜索条件。
- 从全局搜索进入批次时，链接额外携带命中的 `case_id`；批次页会自动选中包含该用例的最深模块/分支，并在右侧用例表高亮该行。如果当前筛选排除了该用例，页面显示“当前筛选下未找到搜索命中用例”的恢复提示。
- 搜索结果表格改为局部 `scroll.x`，1024 宽度下不产生页面级横向溢出。
- 工作台 `/review` 区分“没有批次”和“批次加载失败”：队列失败显示页面级警告和“重试队列”，列表失败显示错误空态和“重试加载”。
- `EmptyState` 支持 `role="alert"`，用于页面级错误态被辅助技术感知。
- API interceptor 对短时间内完全相同的错误 toast 做去重，避免工作台 4 个队列 + 1 个列表并发失败时刷屏。
- 工作台状态筛选写入 URL，例如 `/review?status=suspended`；刷新、后退或从批次页返回时能恢复同一工作队列。
- 从工作台队列/批次表进入批次页时带上 `from=review&status=...`，批次页顶部显示“返回工作台（待澄清/失败/生成中/待审核）”，避免 QA 从待办进入后丢失上下文。
- 从通知中心进入批次页时也会带上工作台上下文：生成完成通知返回“待审核”，失败通知返回“失败”，挂起通知返回“待澄清”。通知入口不再裸跳批次页。
- 失败批次会在阶段进度区展示失败阶段和后端透传的 `stage.error_message`；如果后端没有返回详细错误，页面明确说明“未返回详细错误”，并提示重试前检查 Worker、Redis 和模型网关。
- 批次审查页的文档/模块目录支持收起；QA 选好范围后可以把页面空间让给右侧用例表，右侧标题区保留当前范围和“展开目录”动作。
- 搜索 `/search` 区分“无匹配结果”和“搜索请求失败”：失败时显示“搜索结果加载失败”“重试搜索”，指标条显示 `- / 加载失败`，不再用 0 条误导用户。
- 用例资产 `/case-library` 区分“暂无资产”和“资产树/系统列表加载失败”：系统列表失败显示页面级错误态；资产树失败时顶部提示、左树、右表都明确“不能据此判断当前系统没有资产”。
- 用例资产批次范围列表加载失败时不再静默变成空下拉：页面保留默认资产浏览，同时显示“批次范围暂时无法加载”“重试批次”，并明确不能据此判断该系统没有历史批次。
- 导出中心 `/exports` 区分“没有导出任务”和“导出列表加载失败”：失败时顶部提示变为 warning，指标条显示 `- / 加载失败`，列表区提供“重试加载”和“新建导出”。

仍然不足：

- 批次工作台已经展示后端现有 `stage.error_message`；但若未来需要“重试历史 / 失败堆栈 / 模型网关状态”这类更完整诊断，仍需要后端提供更结构化的运行日志或任务事件流。
- 1024 宽度下批次页为保证表格可操作，树表会上下堆叠；现在目录可以收起，能降低选定范围后的滚动长度，但真实大批量用例仍需要继续做运行态截图和性能验证。
- 工作台返回上下文目前覆盖从 `/review`、通知中心、`/search`、知识库生成和文档详情生成进入批次页的场景；仍需关注未来新增入口是否同步补齐返回语义。
- 文档详情返回上下文目前覆盖从知识库列表和全局搜索进入详情的场景；从关联文档表格或直接 URL 进入时仍返回项目/系统，避免没有明确来源时构造错误路径。
- 文档关联列表的真实后端接口目前只返回关联 ID 与源/目标文档 ID，不返回关联文档标题和类型；前端为了不白屏会用文档 ID 做兜底展示。若要达到更好的 QA 追溯体验，后端应返回目标文档标题、类型和方向，或新增详情接口。
- 系统列表搜索/排序目前只作用于当前页；如果系统数量继续增多，需要后端支持全局搜索、排序和状态过滤，否则用户跨页找系统仍会费劲。
- 用例资产页没有做虚拟树/虚拟表；当前通过局部滚动和分页降低滚动成本，但真实 2000+ 用例资产仍需继续做性能验证。
- 长标题目前采用 2 行截断 + 完整 `title`/详情抽屉的后台表格实践；如果未来标题本身承载关键差异，需要补“展开标题”或“密度切换”，不能只依赖 hover。
- 导出列表接口当前不返回 `total_cases`、`completed_at`、`error_message` 的完整列表字段；前端已兼容缺省值，但真实环境下失败原因可能仍不如详情接口完整。
- 新建导出弹窗能区分选项加载失败和真实无可导出批次；但如果未来要解释“为什么某个运行中/失败/挂起批次不可导出”，还需要更明确的后端批次可导出原因或前端状态说明。
- 用例资产页已解释默认批次范围规则；但如果要精确显示“每份文档实际命中的默认批次清单”，仍需要后端返回当前生效批次元信息。

### 2. 是否误伤完整生成测试用例主流程

结论：目前没有发现阻断。

- 未改动后端生成 pipeline、LLM 调用、worker、case 生成/核验逻辑。
- `/systems/:systemId/documents`、`/batches/:batchId`、`/case-library`、`/exports` 等旧路由保留。
- 批次工作台的澄清、审查、迭代、落库逻辑只换了页面头和筛选条容器，业务回调未改。

风险：

- `/` 默认从 `/systems` 改为 `/review`，这是产品动线选择，不是技术破坏；若用户强依赖首页进系统列表，需要在发布说明里说明。

### 3. 是否只是换皮

结论：不是纯换皮，但本轮仍偏“骨架层”。

不是换皮的证据：

- 工作台默认筛选语义变了，能看到运行/失败/待澄清等批次。
- 主导航的信息架构变了，入口顺序按 QA 工作流重排。
- 入口页增加了统计摘要、页面职责说明和空态恢复路径。
- 系统列表从卡片墙变成了可扫描的表格，并把“上传资料/发起生成/进入知识库”放到每个系统的主上下文中。
- 用例资产现在区分主集候选、全部资产、待处理资产，并把上传/生成恢复路径放回页面顶部。
- 用例资产默认视图里若仍有待审债务，会主动给出下一步审查动作，减少首次使用本平台的 QA 把“主集候选”误读为“可直接交付资产”的风险。
- 工作台有了真正的状态分组待办队列，而不是只靠一个全量批次表。
- 知识库列表可以直接发起生成，不再强迫用户先进入文档详情页寻找按钮。
- 知识库/文档详情发起生成进入批次后保留返回来源，不再让 QA 在生成工作台里丢失“刚才从哪份资料开始”的上下文。
- 知识库上传类型现在是上传前显性决策，不再只是上传结果里的类型标签。
- 文档详情不再只是字段展示页，而是把资料状态、关联上下文和生成动作放在同一决策面板里。
- 批次工作台不再只是“阶段条 + 筛选 + 树表”，而是把“当前批次状态 -> 下一步动作 -> 阶段证据 -> 按模块审查 -> 迭代/落库”串成了一个执行流。
- 导出中心不再只是任务 ID 表，而是围绕“生成交付文件、等待完成、下载、失败重建”组织。
- 全局搜索不再只是“关键词 + 结果表”，而是围绕“确认覆盖 -> 定位到批次 -> 回到来源文档”组织。
- 全局搜索的追溯链现在保留返回路径：QA 从结果进入批次或文档后，可以回到原搜索结果继续比较其他覆盖，不需要重输关键词和筛选条件。
- 全局搜索进入批次后会定位并高亮命中用例，减少 QA 到批次页后重新搜索同一标题的重复动作。
- 工作台不再把接口失败伪装成“暂无批次”，而是明确告诉用户当前无法确认待处理事项，并给出重试动作。
- 通知入口不再把 QA 扔到孤立批次页；处理完一条通知后可以通过批次页顶部返回对应工作台队列继续处理同类待办。
- 失败批次不再只给一个泛红状态；QA 可以直接看到失败阶段、错误原因或“未返回详细错误”的明确兜底，再决定是否重新入队。
- 批次审查页目录从“持续占位的导航栏”变成“可收起的定位工具”；这更接近专业 QA 选定模块后集中处理用例表的工作方式。
- 批次范围默认规则不再让 QA 猜；页面直接说明默认按每份文档最新可见批次聚合，并区分批次列表加载失败和无可见批次。
- 导出中心的新建弹窗也不再让 QA 猜：系统/批次选项接口失败会直接暴露，并复用同一套可见批次规则，避免交付出口和资产浏览入口状态口径漂移。

仍需继续的地方：

- 页面级错误态仍需继续推广到其他入口页；本轮先修了工作台这个最高优先级入口。
- 文档详情从知识库和搜索进入时已可通过 URL query 精确返回原上下文；关联文档继续保持普通文档跳转，避免没有明确来源时错误返回。
- 视觉 token 只是轻量集中，尚未形成完整设计系统规范。
- 批次页还没有做真实大批量用例下的虚拟滚动/性能验证；当前只验证了布局与主动作可见。

### 4. 是否过度抽象

结论：当前抽象可接受。

- 新组件只负责页面壳、标题、筛选条、指标条、分栏、空态，没有夹带业务语义。
- 用例资产树表仍复用阶段 C 的 `CaseAssetTree` / `CaseAssetTable`，没有重新复制树逻辑。
- `StatusTag` 已在工作台批次状态中接入，避免新增组件只是“设计系统摆设”。

### 5. 视觉与布局验证

验证结果：

- `npm run build`：通过。
- `npm run test:case-assets`：4 passed。
- `npm run lint`：失败，原因是仓库 `web` 目录没有 ESLint 配置文件，非本轮改动引入。
- Playwright 关键路由冒烟：
  - `/review`
  - `/systems`
  - `/case-library`
  - `/search`
  - `/exports`
- 1440 宽度：五个路由均有内容、导航可见、无 pageerror。
- 1024 宽度：五个路由均无页面级横向溢出。
- 工作台补充验证：
  - 1440/1024 宽度均能看到待澄清、失败、生成中、待审核四个队列。
  - 4 个队列“筛选”按钮可见。
  - 点击第一个队列“筛选”后，页面出现当前状态“待澄清”语义。
- 文档详情补充验证：
  - 1440/1024 宽度均能看到“文档详情”“生成测试用例”“关联文档”等主入口。
  - 点击“生成测试用例”后出现确认弹窗，不直接触发生成。
  - 页面根节点和内容区均无横向溢出。
- 文档详情真实 Chrome 回归：
  - 真实接口 `GET /api/v1/documents/:id/associations` 返回 `{items,total,page,per_page,total_pages}`，修复前详情页会白屏。
  - 修复后访问 `127.0.0.1:3002/documents/effbf86d-3719-4010-b2b9-b8a66c925b80?from=knowledge&system_id=6b0ea53c-f734-4bc9-8506-663d47107b9d` 可正常渲染“文档详情”“生成测试用例”“关联文档”。
  - 页面显示面包屑“项目/系统 / 知识库 / 文档详情”和“返回知识库”按钮。
  - 点击“返回知识库”后回到 `/systems/6b0ea53c-f734-4bc9-8506-663d47107b9d/documents`，没有白屏。
  - 新增 `normalizeDocAssociations` 单测覆盖分页空响应、分页关联行、旧 `{direct, indirect}` shape 三类输入。
- 知识库上传类型补充验证：
  - Playwright mock `/systems/:id/documents`、`/systems/:id` 和上传接口，不触发真实后端生成。
  - 1440/1024 宽度均能看到“上传前先选择资料类型”“本次上传：PRD”和拖拽区“本次将以 PRD 入库”。
  - 选择“其他”后出现风险提示；上传文件会出现“确认以其他类型入库”确认弹窗。
  - 点击继续上传后请求参数为 `doc_type=other`，上传结果回显“其他”类型。
  - 1024 宽度下文档标题列和“生成用例”按钮均可见，页面无横向溢出，控制台无 error。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/knowledge-upload-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/knowledge-upload-narrow.png`
- 批次工作台补充验证：
  - Playwright mock `/batches/batch-visual` 和 `/systems/sys-1/case-tree`，不触发真实生成/落库。
  - 1440/1024 宽度均能看到“批次状态、待审、需修改、待澄清”等状态指标。
  - 1440/1024 宽度均能看到“确认、需修改、删除、触发迭代、落库归档”等核心动作。
  - 1440/1024 宽度均无页面级横向溢出，控制台无 pageerror / error。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/workbench-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/workbench-narrow.png`
- 系统列表补充验证：
  - Playwright mock `/systems`，不触发真实后端数据。
  - 1440/1024 宽度均能看到资料状态、文档数、批次数、最近活动。
  - 1440/1024 宽度均能看到上传资料、发起生成、进入知识库、编辑、删除。
  - 当前页关键词筛选可生效：输入“漫剧”后仅保留“漫剧批创系统”。
  - 1440/1024 宽度均无页面级横向溢出，控制台无 pageerror / error。
  - 本轮代码审查补齐 `/systems` 加载失败态：失败时指标条不会用 0 派生“待上传资料”，列表区显示 `role=alert` 的“系统列表加载失败”和“重试加载”。
  - 本轮真实接口回归：通过 Vite 同源代理请求 `/api/v1/systems?page=1&per_page=1`，`漫剧批创系统` 返回 `document_count=1`、`batch_count=3`，系统入口不再依赖缺字段兜底成 0。
  - 本轮工具限制：Computer Use 未拿到 Chrome 窗口句柄，未新增浏览器截图；本轮证据为代码审查、真实接口响应、`npm run build` 和既有前端模型测试。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/systems-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/systems-narrow.png`
- 用例资产补充验证：
  - Playwright mock `/case-library`、`/systems/options`、`/systems/:id/batches`、`/systems/:id/case-tree`，不触发真实后端生成。
  - 1440/1024 宽度均能看到主集候选、全部资产、待处理资产、上传/生成、文档 / 模块结构。
  - 1440/1024 宽度均无页面级横向溢出；表格横向空间限制在表格内部滚动。
  - 1440/1024 宽度切换“全部资产”后仍能看到重复标记指标，控制台无 pageerror / error。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-narrow.png`
- 导出中心补充验证：
  - Playwright mock `/exports`、`/systems/options`、`/systems/:id/batches`，不触发真实导出 worker。
  - 1440/1024 宽度均能看到“用例交付导出”、可下载文件指标、失败恢复提示和下载文件入口。
  - 状态筛选选择“已完成”后，请求后端筛选并只展示完成任务。
  - 新建导出弹窗可选择系统和批次；点击创建后请求体为 `{scope:'batch', format:'markdown', batch_id:'batch-1'}`。
  - 1440/1024 宽度均无页面级横向溢出，下载入口在主列可见，控制台无 error。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/exports-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/exports-narrow.png`
- 全局搜索补充验证：
  - Playwright 访问 `/search`，不触发真实搜索请求。
  - 1440/1024 宽度均能看到“输入关键词开始检索用例资产”和“浏览用例资产”初始空态。
  - 1024 宽度能看到“系统 / 优先级 / 审核状态”筛选标签。
  - 1440/1024 宽度均无页面级横向溢出。
  - 本轮补充搜索命中定位：`npm run test:case-assets` 覆盖 `findCaseAssetNodeKeyForCase`，确认能返回包含目标用例的最深分支节点；`npm run build` 确认 `case_id` URL 链路、批次页高亮参数和共享表格类型均可通过构建。
  - 本轮尝试用 Playwright mock 验证“搜索 -> 定位到批次 -> 高亮行”，但当前仓库根目录和 `web` 目录均未安装 `playwright` 包，未新增浏览器截图；因此本轮运行态证据以构建、模型测试和代码审查为准。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/search-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/search-narrow.png`
- 工作台错误恢复补充验证：
  - Playwright mock `/api/v1/batches` 返回 503，不触发真实后端。
  - 1024 宽度能看到“待办队列加载失败”“批次列表加载失败”“重试队列”“重试加载”。
  - 错误空态存在 `role=alert`，便于辅助技术识别。
  - API toast 去重生效，5 个并发失败请求只显示 1 条“服务暂时不可用”。
  - 正常 mock 数据下 1440 宽度仍能看到待审核队列、批次标题和“去审核”动作，无误报“加载失败”。
  - 本轮补充代码审查确认：`GET /batches` 后端仓库层 `find_all` 已按 `TestBatch.created_at.desc()` 排序；前端待办队列现在请求最近 8 条，默认显示 3 条并可展开，且“查看全部 N 条”继续复用下方状态筛选分页。
  - 本轮 `npm run build` 通过，确认展开状态、队列文案和时间格式化没有 TypeScript/Vite 构建问题。
  - 本轮 `npm run test:case-assets` 通过，5 个现有前端模型测试未回归。
  - 本轮 `npm run lint` 仍失败，原因是 `web` 目录缺 ESLint 配置文件，属于已知基建缺口，不是本轮 UI 改动引入。
  - 1440/1024 宽度均无页面级横向溢出。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/review-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/review-ok-desktop.png`
- 工作台与批次页上下文补充验证：
  - `/review?status=suspended` 会初始化为“待澄清”筛选，状态变更会同步更新 URL。
  - 从待澄清、失败、生成中、待审核队列进入批次页时，URL 带 `from=review&status=<status>`。
  - 批次页只在来源为 `review` 时展示返回按钮；按钮按来源状态返回 `/review?status=<status>`。
  - 该改动只读写前端 URL 和页面导航，不改变批次详情、轮询、澄清、迭代、落库等后端契约。
  - 真实 Chrome 冒烟：访问 `127.0.0.1:3002/review?status=suspended` 时，页面显示“当前状态 待澄清”，下拉恢复为“待澄清”，页面不白屏。
  - 真实 Chrome 冒烟：从待审核队列点击“漫剧批创初版功能PRD”后进入 `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4?from=review&status=pending_review`，批次页顶部显示“返回工作台（待审核）”。
  - 真实 Chrome 冒烟：点击“返回工作台（待审核）”后回到 `/review?status=pending_review`，指标和下拉均恢复为“待审核”。
- 入口页错误恢复补充验证：
  - Playwright mock `/search`、`/case-library`、`/exports` 的 503，不触发真实后端。
  - `/search` 失败时能看到“搜索结果加载失败”“重试搜索”，指标条显示“加载失败”，1024 宽无页面级横向溢出。
  - `/case-library` 系统列表失败时能看到“系统列表加载失败”“重试加载”；资产树失败时能看到“用例资产加载失败”“不能据此判断当前系统没有资产”，指标条显示“加载失败”，1024 宽无页面级横向溢出。
  - `/exports` 失败时能看到“导出任务列表暂时无法加载”“导出任务加载失败”“重试加载”，指标条显示“加载失败”，1024 宽无页面级横向溢出。
  - 正常 mock 数据下 `/search`、`/case-library`、`/exports` 仍能显示结果/资产/导出任务，未阻断成功路径。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/search-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/search-success-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-tree-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-system-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-success-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/exports-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/exports-success-narrow.png`
- 用例资产批次范围补充验证：
  - Playwright mock `/systems/:id/batches` 返回 503 时，页面仍展示资产树和用例表，且能看到“批次范围暂时无法加载”“不能据此判断该系统没有历史批次”“重试批次”。
  - 正常 mock 数据下，批次范围下拉可展开并看到“账号授权 PRD · 已完成”批次选项，且没有失败 warning。
  - 两条路径 1024 宽均无页面级横向溢出。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-batch-error-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-batch-success-narrow.png`
- 用例资产大数据密度补充验证：
  - Playwright mock 3 份文档、42 个模块、504 个分支节点、840 条用例，包含超长模块名和超长用例标题，不触发真实后端生成。
  - 修复前无页面级横向溢出，但 20 条分页因超长标题导致页面高度过长：1440 宽 `bodyHeight=3973`，1024 宽 `bodyHeight=4694`。
  - 修复后树节点单行省略、表格标题 2 行截断且保留完整 `title`；1440 宽 `bodyHeight=2353`，1024 宽 `bodyHeight=2986`。
  - 修复后 1440/1024 宽均无页面级横向溢出；`firstTitleBoxHeight=40.59375`，树节点存在完整原生 `title`，分页显示“共 840 条”。
  - 批次工作台 `/batches/:batchId` 同步冒烟：1024 宽下长标题不会挤掉“确认、需修改、删除”，无页面级横向溢出。
  - 截图产物：
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-large-clamped-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-large-clamped-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-large-clamped-search-desktop.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/case-library-large-clamped-search-narrow.png`
    - `.trellis/tasks/07-04-ux-information-architecture-visual/screenshots/workbench-clamped-narrow.png`

## 当前结论

本轮可以作为阶段 D 的第一版“信息架构与视觉骨架 + 关键工作流入口”提交，但不应宣称 UI/UX 重构完成。

建议下一步继续做：

- 审查中心 `/review` 和批次页之间继续增强上下文衔接，例如从待办队列进入后保留来源筛选。
- 针对真实大批次数据继续验证性能、树折叠策略和表格分页体验。
- 继续推进真实大批量数据下的性能与交互验证，并评估是否需要后端返回“默认最新可见批次”的选择依据。
