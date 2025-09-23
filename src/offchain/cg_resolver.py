import os, json, time, requests
from typing import Optional, Dict, Any, List
from ..config import settings
from ..logger import get_logger
log = get_logger(__name__)

CG_LIST_URL = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"

class CGResolver:
    def __init__(self):
        os.makedirs(settings.CACHE_DIR, exist_ok=True)
        self.path = os.path.join(settings.CACHE_DIR, "cg_list.json")
        self.by_id: Dict[str, dict] = {}
        self.by_symbol: Dict[str, List[dict]] = {}
        self.by_name: Dict[str, dict] = {}
        self._load_or_fetch()

    def _load_or_fetch(self):
        need = True
        if os.path.exists(self.path):
            age = (time.time() - os.path.getmtime(self.path)) / 60
            if age <= settings.CG_LIST_TTL_MIN:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self._build(data)
                log.info("CGResolver: cache loaded (age=%.1f min)", age)
                need = False
        if need:
            r = requests.get(CG_LIST_URL, timeout=30)
            r.raise_for_status()
            data = r.json()
            json.dump(data, open(self.path, "w", encoding="utf-8"))
            self._build(data)
            log.info("CGResolver: list fetched (%d)", len(data))

    def _build(self, data: List[Dict[str, Any]]):
        self.by_id.clear(); self.by_symbol.clear(); self.by_name.clear()
        for it in data:
            cid = (it.get("id") or "").strip()
            sym = (it.get("symbol") or "").strip().upper()
            name = (it.get("name") or "").strip()
            plats = it.get("platforms") or {}
            eth = plats.get("ethereum")
            if not isinstance(eth, str) or not eth.startswith("0x") or len(eth) != 42:
                eth = None
            rec = {"id": cid, "symbol": sym, "name": name, "eth": eth}
            if cid:
                self.by_id[cid] = rec
            if sym:
                self.by_symbol.setdefault(sym, []).append(rec)
            if name:
                self.by_name[name.lower()] = rec

    def lookup(self, *, symbol: Optional[str], name: Optional[str]) -> Optional[dict]:
        """
        Retourne le meilleur enregistrement CoinGecko pour (symbol, name).
        Priorité:
           1) symbol exact avec adresse ETH si possible
           2) sinon symbol exact
           3) sinon name exact
        """
        sym = (symbol or "").upper()
        if sym and sym in self.by_symbol:
            cands = self.by_symbol[sym]
            # préfère ceux avec ETH
            cands = sorted(cands, key=lambda r: (0 if r.get("eth") else 1, r.get("id") or "zz"))
            return cands[0]
        nm = (name or "").lower()
        if nm and nm in self.by_name:
            return self.by_name[nm]
        return None
