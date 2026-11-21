# 结构说明

`src/models/tables.py` 定义关系结构。API 启动时通过 `src/migrations.py` 的 `reconcile()` 显式创建演示库的表，并为旧演示卷补齐新增的可空列。

- 补齐只做 `ALTER TABLE ... ADD COLUMN`，不改写既有行，可重复执行。
- 这是演示用的就地补列，不构成正式迁移方案。已有部署升级时应引入版本化迁移工具（如 Alembic），把 `business_runs.payload`、`payload_digest`、`version`、`attempts`、`lease_expires_at`，`business_evidence.payload_digest`、`version`、`attempt`、`created_at`，以及 `audit_events.case_id`、`run_id`、`evidence_id` 纳入受控迁移。
- 旧执行没有冻结快照，`payload` 为空；worker 领取时会将其标记为失败而不是重新读取档案，以免用新口径冒充排队时的输入。
