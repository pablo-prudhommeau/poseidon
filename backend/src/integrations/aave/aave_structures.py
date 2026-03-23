from pydantic import BaseModel


class AaveLiveMetrics(BaseModel):
    supply_apy: float
    asset_out_price_usd: float
