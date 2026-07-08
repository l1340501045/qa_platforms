# 本地数据库表字段备注补齐

## Goal

让用户在 Navicat 查看本地 PostgreSQL 数据库 `qa_platforms` 时，能直接看到表和字段的中文备注，降低理解数据结构的成本。

## Confirmed Facts

- 本地库连接信息来自 `.env` 和 `docker-compose.infra.yml`：`localhost:5434`、库名 `qa_platforms`、用户 `postgres`。
- 当前本地库存在业务相关 schema：`public`、`knowledge`、`testcase`。
- 当前用户诉求是补齐本地库表备注和字段备注，便于在 Navicat 中查看。

## Requirements

- 只补充 PostgreSQL 表注释和字段注释，不修改表结构、不修改业务数据。
- 覆盖当前本地库中 `public`、`knowledge`、`testcase` schema 下的表。
- 备注使用中文，表达业务含义；技术/框架内部表也要给出可理解说明。
- 执行前先读取数据库实际 schema，按当前真实表字段生成 `COMMENT ON` 语句。
- 执行后抽查数据库系统目录，确认表备注和字段备注已写入。

## Acceptance Criteria

- [x] Navicat 中当前本地库的主要表能显示中文表备注。
- [x] Navicat 中当前本地库的主要字段能显示中文字段备注。
- [x] 数据库业务数据未被增删改，只写入 comment 元信息。
- [x] 备注覆盖 `public`、`knowledge`、`testcase` schema 下当前存在的表。

## Verification

- 执行 `COMMENT ON TABLE` / `COMMENT ON COLUMN` 语句补齐本地 PostgreSQL comment 元信息。
- 验证结果：`public`、`knowledge`、`testcase` schema 下 24 张表、220 个字段均已有备注，缺失数为 0。

## Out of Scope

- 不为未来尚不存在的表预生成备注。
- 不创建 Alembic 迁移文件，除非用户后续要求把备注持久化进代码仓库。
- 不调整数据库表名、字段名、索引或约束。
