-- 增量迁移：任务级 TTS 音色/语速 + 片尾开关
--
-- schema.sql 只使用 CREATE TABLE IF NOT EXISTS，已存在的 tasks 表不会
-- 因修改建表语句而新增列，因此需要单独执行 ALTER TABLE。
-- SQLite 不支持 ADD COLUMN IF NOT EXISTS，重复执行会报错，
-- 所以由 deploy-backend.yml 中的「应用增量迁移（幂等）」步骤逐条执行并忽略已存在的错误。

ALTER TABLE tasks ADD COLUMN enable_outro BOOLEAN DEFAULT TRUE;
ALTER TABLE tasks ADD COLUMN tts_voice TEXT;
ALTER TABLE tasks ADD COLUMN tts_speed REAL DEFAULT 1.0;