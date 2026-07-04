# UI 验收预检覆盖生成配置自审

## 结论

本次修正方向成立。真实跑批结果高度依赖生成配置，如果只检查 `.env` 模型而不检查前端传入的 `generation_config`，周一可能在错误配置下跑出一批不可比较的数据。

## 自审问题

### 1. 是否改变了生成逻辑

没有。脚本只读解析 `batchApi.ts`、`settings.py` 和 `pipeline/config.py`，没有 import 业务模块、没有启动服务、没有写数据库，也没有修改 `src/testcase_generator/**`。

### 2. 是否过度依赖脆弱字符串解析

有一点风险，但当前是可接受的预检脚本。Python pipeline 配置使用 `ast.literal_eval`，前端解析复用了现有测试 `test_frontend_best_practice_config_matches_backend_contract` 的轻量解析方式。settings 默认值用正则读取类型标注行，若结构漂移会 fail fast。

### 3. 是否让 runbook 变复杂

没有。runbook 仍建议先跑预检，手工 `grep/rg` 只作为失败排查手段。

## 判定

可以收口。后续如果生成配置项继续增加，应优先扩展预检中的 `EXPECTED_GENERATION_CONFIG`，避免真实验收依赖人工目测。
