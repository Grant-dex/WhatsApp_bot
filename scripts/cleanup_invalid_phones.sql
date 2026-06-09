-- =============================================================================
-- WhatsApp Bot - 无效电话号码清理脚本
-- 用途：检测并清理数据库中"姓名当号码"存储的无效记录
-- 用法：sqlite3 data/customers.db < scripts/cleanup_invalid_phones.sql
--       或在 SQLite 命令行中 .read scripts/cleanup_invalid_phones.sql
-- =============================================================================

-- ── 第一步：统计检测 ──────────────────────────────────────────────────────
.print '========================================'
.print '  无效电话号码检测报告'
.print '========================================'

-- 总客户数
SELECT '总客户数' AS 指标, COUNT(*) AS 数量 FROM customers
UNION ALL
-- 无效号码数（包含字母但不是国际号码的）
SELECT '无效号码总数' AS 指标, COUNT(*) FROM customers
WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*'
UNION ALL
-- 无效号码中有对话记录的
SELECT '其中：有对话记录' AS 指标, COUNT(DISTINCT c.id) FROM customers c
JOIN conversations conv ON c.id=conv.customer_id
WHERE c.phone GLOB '*[A-Za-z]*' AND c.phone NOT GLOB '+*'
UNION ALL
-- 无效号码中有活跃跟进计划的
SELECT '其中：有活跃跟进计划' AS 指标, COUNT(DISTINCT c.id) FROM customers c
JOIN follow_up_schedule fs ON c.id=fs.customer_id AND fs.active=1
WHERE c.phone GLOB '*[A-Za-z]*' AND c.phone NOT GLOB '+*'
UNION ALL
-- 无对话记录可安全删除的
SELECT '其中：无对话可安全删除' AS 指标, COUNT(*) FROM customers c
WHERE c.phone GLOB '*[A-Za-z]*' AND c.phone NOT GLOB '+*'
  AND NOT EXISTS (SELECT 1 FROM conversations WHERE customer_id=c.id);

.print ''
.print '──────── 无效号码样本（前 20 条）────────'
SELECT id, phone AS 存储值, name AS 姓名, status AS 状态,
       (SELECT COUNT(*) FROM conversations WHERE customer_id=c.id) AS 对话数
FROM customers c
WHERE c.phone GLOB '*[A-Za-z]*' AND c.phone NOT GLOB '+*'
ORDER BY c.id
LIMIT 20;

-- ── 第二步：执行清理（取消注释需要的操作）────────────────────────────────

.print ''
.print '========================================'
.print '  请根据需要执行以下操作：'
.print '========================================'
.print ''
.print '操作 A: 删除无对话记录的所有无效号码客户'
.print '操作 B: 将所有无效号码客户标记为 inactive'
.print '操作 C: 将所有无效号码客户标记为 inactive + 暂停跟进计划'
.print ''
.print '请取消注释下方对应的 SQL 语句后重新运行。'

-- ── 操作 A：安全删除（无对话记录+无跟进计划）─────────────────────────────
/*
DELETE FROM sent_followups WHERE customer_id IN (
    SELECT id FROM customers
    WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*'
      AND NOT EXISTS (SELECT 1 FROM conversations WHERE customer_id=customers.id)
);
DELETE FROM follow_up_schedule WHERE customer_id IN (
    SELECT id FROM customers
    WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*'
      AND NOT EXISTS (SELECT 1 FROM conversations WHERE customer_id=customers.id)
);
DELETE FROM customers
WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*'
  AND NOT EXISTS (SELECT 1 FROM conversations WHERE customer_id=customers.id);

SELECT '已安全删除 ' || changes() || ' 个无效号码客户（无对话记录）' AS 结果;
*/

-- ── 操作 B：标记为 inactive ──────────────────────────────────────────────
/*
UPDATE customers SET
    status = 'inactive',
    notes = COALESCE(notes, '') || ' [自动标记：电话号码无效 - ' || datetime('now') || ']',
    updated_at = datetime('now')
WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*';

SELECT '已将 ' || changes() || ' 个无效号码客户标记为 inactive' AS 结果;
*/

-- ── 操作 C：标记 inactive + 暂停跟进 ─────────────────────────────────────
/*
UPDATE follow_up_schedule SET active = 0
WHERE customer_id IN (
    SELECT id FROM customers
    WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*'
);

UPDATE customers SET
    status = 'inactive',
    notes = COALESCE(notes, '') || ' [自动标记：电话号码无效 - ' || datetime('now') || ']',
    updated_at = datetime('now')
WHERE phone GLOB '*[A-Za-z]*' AND phone NOT GLOB '+*';

SELECT '已完成：标记 inactive + 暂停跟进计划' AS 结果;
*/
