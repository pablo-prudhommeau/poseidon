# Poseidon

> ⚠️⚠️⚠️⚠️ **EXPERIMENTAL SOFTWARE - HIGH RISK WARNING** ⚠️⚠️⚠️⚠️
> 
> Poseidon is currently in an **ACTIVE DEVELOPMENT (alpha)** stage. It is designed to interact with **real financial assets** and decentralized protocols. 
> 
> **UNLESS EXPLICITLY TESTED IN `PAPER_MODE`, DO NOT USE THIS SOFTWARE WITH YOUR LIVE FUNDS.**
> 
> Use at your own risk. The authors and contributors are not responsible for any financial losses, bugs, or liquidation events. Always start with a dedicated, isolated wallet with minimal funds for initial testing.

---

## 🏛️ System Architecture

```text
                      ┌──────────────────────────────────────────────────────────┐
                      │                    POSEIDON FRONTEND                     │
                      └──────────────┬──────────────────────────────┬────────────┘
                                     │                              │
                                     │      REST / WebSockets       │
                                     │                              │
                      ┌──────────────▼──────────────────────────────▼────────────┐
                      │                     POSEIDON BACKEND                     │
                      └──────────────┬──────────────┬──────────────┬─────────────┘
                                     │              │              │
                      ┌──────────────▼──────┐┌──────▼──────┐┌──────▼─────────────┐
                      │   AI STRATEGY HUB   ││  DCA ENGINE ││   LIQUIDITY WATCH  │
                      │   (OpenAI GPT-5)    ││             ││   (Aave Sentinel)  │
                      └──────────────┬──────┘└──────┬──────┘└──────┬─────────────┘
                                     │              │              │
                      ┌──────────────▼──────────────┴──────────────▼─────────────┐
                      │                 MULTI-CHAIN CONNECTOR                    │
                      ├──────────────────────────────┬───────────────────────────┤
                      │  Ethereum / Solana / AVX     │      AAVE PROTOCOL        │
                      │  DexScreener / Li.Fi         │     (Supply/Borrow)       │
                      └──────────────────────────────┴───────────────────────────┘
```

---

## ⚡ Core Pillars

### 1. High-Frequency AI Trading Bot
A multi-chain, highly configurable execution engine designed for speed and precision.
*   **AI-Driven Analysis**: Leverages OpenAI (GPT-5 Mini) to perform real-time chart analysis via automated screenshots (Playwright).
*   **Multi-Chain Execution**: Native support for **Ethereum**, **Solana**, and **Avalanche**.
*   **Granular Configuration**: Advanced momentum scoring, volume monitoring, and liquidity thresholds.
*   **Sentiment & Trend Integration**: Real-time data fetching from DexScreener and custom trend detection algorithms.

### 2. Ultra-Smart DCA (Dollar Cost Averaging)
Next-generation DCA engine deeply integrated with the **Aave ecosystem**.
*   **Advanced Indicators**: Uses **EMA50** (Exponential Moving Average) to defer buys during market overheating and optimize entry points.
*   **PRU Optimization**: Focuses on **Unit Cost Price (Prix de Revient Unitaire)** synchronization to ensure long-term profitability.
*   **Seamless Relooping**: Dynamic management of supply/borrow positions to maximize capital efficiency.

### 3. Aave Sentinel (Liquidity Watch)
An autonomous monitoring brick dedicated to capital preservation and liquidation prevention.
*   **Health Factor Oversight**: Continuous real-time monitoring of Aave Health Factors.
*   **Automated Rescue**: Automatically manages collateral and repays debt to maintain safety thresholds.
*   **Risk Mitigation**: Designed to react faster than human intervention during extreme market volatility.
*   **Telegram Alerts**: Direct integration for instant notification of critical health status changes.

---

## 🛠️ Technology Stack

| Component | Stack |
| :--- | :--- |
| **Frontend** | Angular 20, PrimeNG 20, TailwindCSS 4, ApexCharts |
| **Backend** | FastAPI (Python 3.11+), SQLAlchemy 2.0, Uvicorn |
| **Automation** | Playwright (Headless Browser), OpenAI SDK |
| **Web3** | Web3.py, Solana-py, Li.Fi Integration |
| **Monitoring** | Telegram Bot API, Structured Logging with Tags |

---

## 🚀 Getting Started

### 1. Environment Configuration
Create a `.env` file in the root directory. **Crucial keys are listed below:**

```bash
# === CORE MODE (KEEP TRUE UNLESS YOU ARE SURE) ===
PAPER_MODE=true

# === API KEYS ===
OPENAI_API_KEY=your_openai_key_here
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# === BLOCKCHAIN RPCs ===
EVM_RPC_URL=https://your-eth-rpc-url
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
AVALANCHE_RPC_URL=https://api.avax.network/ext/bc/C/rpc

# === SECRETS / WALLETS ===
# Use mnemonics or private keys for execution (STAY SAFE)
EVM_MNEMONIC="your twelve words mnemonic here..."
SOLANA_SECRET_KEY_BASE58="your_solana_private_key"
AAVE_MNEMONIC="mnemonic_for_aave_operations"

# === DATABASE ===
DATABASE_URL="sqlite:///./data/poseidon.db"
```

### 2. Launch with Docker
```bash
docker-compose up --build
```

---

## ⚖️ Final Disclaimer

> **DO NOT DEPLOY WITHOUT LIVE TESTING IN PAPER MODE.**
> This software is provided "as is", without warranty of any kind. Automated trading involves significant risk of capital loss. The DCA algorithms and AI analysis can fail during extreme market volatility. Ensure your `PAPER_MODE` is set to `true` for at least 48 hours before considering any real-money interactions.