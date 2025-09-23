# src/main.py (extrait pertinent)
import time
from web3 import Web3
from src.logger import init_logging, get_logger
from src.config import settings
from src.offchain.trending_job import TrendingJob

log = get_logger(__name__)

def init_web3():
    url = (settings.QUICKNODE_URL or "").strip()
    if not url:
        log.info("No QUICKNODE_URL provided → running OFFCHAIN only.")
        return None

    if url.startswith("ws"):
        # 1) Tentative WebsocketProviderV2 (si dispo dans ta version)
        prov_cls = getattr(Web3, "WebsocketProviderV2", None)
        if prov_cls:
            try:
                w3 = Web3(prov_cls(url))
                if w3.is_connected():
                    log.info("Using WebsocketProviderV2")
                    return w3
            except Exception as e:
                log.debug("WebsocketProviderV2 failed: %s", e)

        # 2) Fallback LegacyWebSocketProvider (toujours dispo avec web3 7.x)
        try:
            w3 = Web3(Web3.LegacyWebSocketProvider(url, websocket_kwargs={"max_size": 10_000_000}))
            if w3.is_connected():
                log.info("Using LegacyWebSocketProvider")
                return w3
        except Exception as e:
            log.debug("LegacyWebSocketProvider failed: %s", e)

        # 3) Dernier recours : convertir WS → HTTP (utile si le nœud refuse WS)
        http_url = url.replace("wss://", "https://").replace("ws://", "http://")
        try:
            w3 = Web3(Web3.HTTPProvider(http_url))
            if w3.is_connected():
                log.warning("WS connect failed; falling back to HTTPProvider")
                return w3
        except Exception as e:
            log.debug("HTTP fallback failed: %s", e)

        log.error("Web3 init: no websocket provider available/working.")
        return None

    # Chemin HTTP direct
    try:
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            log.info("Using HTTPProvider")
            return w3
        log.error("HTTPProvider connected=False")
    except Exception as e:
        log.exception("HTTPProvider init error: %s", e)
    return None


def main():
    init_logging()
    log.info("Starting Poseidon (PAPER=%s)", settings.PAPER_MODE)

    w3 = init_web3()
    if w3:
        try:
            log.info("Connected=%s start_block=%s", w3.is_connected(), w3.eth.block_number)
        except Exception as e:
            log.debug("Block number fetch failed: %s", e)

    trending = TrendingJob(w3)

    while True:
        try:
            trending.run_once()
        except Exception as e:
            log.exception("Trending loop error: %s", e)
        time.sleep(settings.TREND_INTERVAL_SEC)


if __name__ == "__main__":
    main()
