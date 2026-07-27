-- Vibe Trading / AI 交易助手 模块数据库迁移
-- 创建时间：2026-07-21
-- 依赖：profiles 表已存在

-- 1. Vibe 会话表
CREATE TABLE IF NOT EXISTS vibe_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    context JSONB DEFAULT '{}',
    summary TEXT,
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS vibe_sessions_user_id_created_at_idx
    ON vibe_sessions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS vibe_sessions_last_message_at_idx
    ON vibe_sessions (user_id, last_message_at DESC);

ALTER TABLE vibe_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can manage own vibe sessions" ON vibe_sessions;
CREATE POLICY "Users can manage own vibe sessions" ON vibe_sessions
    FOR ALL USING (auth.uid() = user_id);

-- 2. Vibe 运行记录表（必须先创建，因为 vibe_messages 外键引用它）
CREATE TABLE IF NOT EXISTS vibe_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    tool_trace JSONB DEFAULT '[]',
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    user_prompt TEXT,
    system_prompt_version TEXT,
    model TEXT,
    decision_basis JSONB,
    raw_request JSONB,
    raw_response JSONB,
    error TEXT,
    cancelled_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS vibe_runs_user_id_created_at_idx
    ON vibe_runs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS vibe_runs_session_id_idx
    ON vibe_runs (session_id);

ALTER TABLE vibe_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can read own vibe runs" ON vibe_runs;
CREATE POLICY "Users can read own vibe runs" ON vibe_runs
    FOR ALL USING (auth.uid() = user_id);

-- 3. Vibe 消息表
CREATE TABLE IF NOT EXISTS vibe_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    run_id UUID REFERENCES vibe_runs(id) ON DELETE SET NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls JSONB,
    tool_call_id TEXT,
    tool_name TEXT,
    tool_input JSONB,
    tool_output_ref TEXT,
    tool_output_summary JSONB,
    cards JSONB,
    event_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS vibe_messages_session_id_created_at_idx
    ON vibe_messages (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS vibe_messages_run_id_idx
    ON vibe_messages (run_id);

ALTER TABLE vibe_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can read own vibe messages" ON vibe_messages;
CREATE POLICY "Users can read own vibe messages" ON vibe_messages
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM vibe_sessions s
            WHERE s.id = vibe_messages.session_id AND s.user_id = auth.uid()
        )
    );

-- 4. Vibe 交易日志草稿表
CREATE TABLE IF NOT EXISTS vibe_journal_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    session_id UUID REFERENCES vibe_sessions(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    direction TEXT,
    planned_size_wu NUMERIC,
    entry_price NUMERIC,
    stop_loss NUMERIC,
    target_price NUMERIC,
    reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS vibe_journal_drafts_user_id_idx
    ON vibe_journal_drafts (user_id, created_at DESC);

ALTER TABLE vibe_journal_drafts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can manage own vibe journal drafts" ON vibe_journal_drafts;
CREATE POLICY "Users can manage own vibe journal drafts" ON vibe_journal_drafts
    FOR ALL USING (auth.uid() = user_id);

-- 5. 触发器：自动更新 vibe_sessions 的 message_count / last_message_at / updated_at
CREATE OR REPLACE FUNCTION update_vibe_session_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE vibe_sessions
    SET message_count = message_count + 1,
        last_message_at = NEW.created_at,
        updated_at = NOW()
    WHERE id = NEW.session_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_vibe_messages_insert ON vibe_messages;
CREATE TRIGGER trg_vibe_messages_insert
    AFTER INSERT ON vibe_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_vibe_session_stats();
