export interface MetricCategory {
    id: string;
    label: string;
    icon: string;
    metricKeys: string[];
}

export const EXPLORATION_CATEGORIES: MetricCategory[] = [
    {
        id: 'liquidity_volume',
        label: 'Volume & Liquidity',
        icon: 'fa-water',
        metricKeys: ['liquidity_usd', 'volume_m5_usd', 'volume_h1_usd', 'volume_h6_usd', 'volume_h24_usd', 'liquidity_churn_h24']
    },
    {
        id: 'momentum',
        label: 'Price Momentum',
        icon: 'fa-bolt',
        metricKeys: ['price_change_m5', 'price_change_h1', 'price_change_h6', 'price_change_h24', 'momentum_acceleration_5m_1h', 'buy_to_sell_ratio']
    },
    {
        id: 'activity',
        label: 'Network Activity',
        icon: 'fa-network-wired',
        metricKeys: ['transaction_count_m5', 'transaction_count_h1', 'transaction_count_h6', 'transaction_count_h24', 'token_age_hours']
    },
    {
        id: 'quality',
        label: 'Quality & Value',
        icon: 'fa-diamond',
        metricKeys: ['quality_score', 'market_cap_usd', 'fully_diluted_valuation_usd', 'dexscreener_boost']
    }
];
export const tradingGridsLeadingColumnLayout = {
    symbol: {
        flex: 0,
        width: 170,
        minWidth: 170,
        maxWidth: 170
    },
    dateTime: {
        flex: 0,
        width: 144,
        minWidth: 144,
        maxWidth: 144
    },
    phaseOrSide: {
        flex: 0,
        width: 124,
        minWidth: 124,
        maxWidth: 124
    },
    qty: {
        flex: 0,
        width: 100,
        minWidth: 100,
        maxWidth: 100
    },
    leadingFifthNumeric: {
        flex: 0,
        width: 112,
        minWidth: 112,
        maxWidth: 112
    }
} as const;