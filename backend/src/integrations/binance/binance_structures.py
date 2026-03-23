from pydantic import BaseModel


class ExponentialMovingAverageAndPrice(BaseModel):
    exponential_moving_average: float
    latest_closing_price: float


class CandlestickData(BaseModel):
    closing_timestamp_milliseconds: int
    closing_price: float
