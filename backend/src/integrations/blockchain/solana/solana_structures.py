from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class JupiterPriceData(BaseModel):
    usdPrice: float
    liquidity: Optional[float] = None
    decimals: Optional[int] = None
    priceChange24h: Optional[float] = None

    model_config = ConfigDict(extra="ignore")


class JupiterQuoteRoutePlanStep(BaseModel):
    ammKey: str
    label: Optional[str] = None
    inputMint: str
    outputMint: str
    feeAmount: Optional[str] = None
    feeMint: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class JupiterQuoteRoutePlan(BaseModel):
    swapInfo: JupiterQuoteRoutePlanStep
    percent: int

    model_config = ConfigDict(extra="ignore")


class JupiterQuoteResponse(BaseModel):
    inputMint: str
    inAmount: str
    outputMint: str
    outAmount: str
    otherAmountThreshold: str
    swapMode: str
    slippageBps: int
    priceImpactPct: str
    routePlan: List[JupiterQuoteRoutePlan]

    model_config = ConfigDict(extra="ignore")


class JupiterSwapRequest(BaseModel):
    quoteResponse: JupiterQuoteResponse
    userPublicKey: str
    wrapAndUnwrapSol: bool = True
    dynamicComputeUnitLimit: bool = True
    prioritizationFeeLamports: str = "auto"


class JupiterSwapResponse(BaseModel):
    swapTransaction: str
    lastValidBlockHeight: Optional[int] = None
    prioritizationFeeLamports: Optional[int] = None
    computeUnitLimit: Optional[int] = None
    prioritizationType: Optional[Dict[str, int]] = None
    dynamicSlippageReport: Optional[Dict[str, str]] = None

    model_config = ConfigDict(extra="ignore")
