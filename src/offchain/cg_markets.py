import requests
from typing import Dict, List
from ..logger import get_logger
log=get_logger(__name__)

# ids -> pct changes; we map via CG list when possible (best effort)
def fetch_pct_changes(ids:List[str])->Dict[str,dict]:
    out={}
    if not ids: return out
    # on coupe en paquets (limite 250 ids par appel)
    CHUNK=200
    for i in range(0,len(ids),CHUNK):
        part=",".join(ids[i:i+CHUNK])
        url=f"https://api.coingecko.com/api/v3/coins/markets"
        params={"vs_currency":"usd","ids":part,"price_change_percentage":"1h,24h"}
        try:
            r=requests.get(url,params=params,timeout=20); r.raise_for_status()
            for x in r.json():
                cid=x.get("id")
                out[cid]={"pct1h":x.get("price_change_percentage_1h_in_currency"),
                          "pct24h":x.get("price_change_percentage_24h_in_currency")}
        except Exception as e:
            log.warning("CG markets failed (chunk %d): %s", i//CHUNK, e)
    return out
