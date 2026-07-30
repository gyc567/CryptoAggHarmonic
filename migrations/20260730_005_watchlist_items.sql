-- Watchlist (自选币种) 数据库迁移
-- 创建时间：2026-07-30
-- 依赖：profiles 表已存在
--
-- 数据来源：Binance USDⓈ-M 永续合约 exchangeInfo
--   contractType ∈ {PERPETUAL, TRADIFI_PERPETUAL}
--   underlyingType ∈ {COIN, EQUITY, COMMODITY, INDEX, KR_EQUITY, HK_EQUITY, PREMARKET}
--   quoteAsset = 'USDT'
-- 后端 app/api/watchlist_routes.py 会把合法 symbol 写入 contract_type/underlying_type
-- 两个字段；前端搜索时用它们做 chip 过滤。

CREATE TABLE IF NOT EXISTS watchlist_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'futures',
    symbol TEXT NOT NULL,
    base_asset TEXT,
    quote_asset TEXT,
    contract_type TEXT,
    underlying_type TEXT,
    underlying_sub_types TEXT[] DEFAULT '{}',
    price_precision SMALLINT,
    quantity_precision SMALLINT,
    is_tradfi BOOLEAN DEFAULT false,
    note VARCHAR(280) NOT NULL DEFAULT '',
    sort_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, market, symbol)
);

CREATE INDEX IF NOT EXISTS watchlist_items_user_id_sort_idx
    ON watchlist_items (user_id, sort_index ASC);
CREATE INDEX IF NOT EXISTS watchlist_items_user_id_created_at_idx
    ON watchlist_items (user_id, created_at DESC);

ALTER TABLE watchlist_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can manage own watchlist items" ON watchlist_items;
CREATE POLICY "Users can manage own watchlist items" ON watchlist_items
    FOR ALL USING (auth.uid() = user_id);

-- 自动更新 updated_at
CREATE OR REPLACE FUNCTION touch_watchlist_items_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_watchlist_items_updated_at ON watchlist_items;
CREATE TRIGGER trg_watchlist_items_updated_at
    BEFORE UPDATE ON watchlist_items
    FOR EACH ROW
    EXECUTE FUNCTION touch_watchlist_items_updated_at();