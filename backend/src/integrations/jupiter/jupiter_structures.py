from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


class JupiterRoutePlanStepSwapInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amm_key: str = Field(alias="ammKey")
    label: str = Field(alias="label")
    input_mint: str = Field(alias="inputMint")
    output_mint: str = Field(alias="outputMint")
    in_amount: str = Field(alias="inAmount")
    out_amount: str = Field(alias="outAmount")
    fee_amount: Optional[str] = Field(default=None, alias="feeAmount")
    fee_mint: Optional[str] = Field(default=None, alias="feeMint")


class JupiterRoutePlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    swap_info: JupiterRoutePlanStepSwapInfo = Field(alias="swapInfo")
    percent: int


class JupiterQuoteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_mint: str = Field(alias="inputMint")
    in_amount: str = Field(alias="inAmount")
    output_mint: str = Field(alias="outputMint")
    out_amount: str = Field(alias="outAmount")
    other_amount_threshold: str = Field(alias="otherAmountThreshold")
    swap_mode: str = Field(alias="swapMode")
    slippage_basis_points: int = Field(alias="slippageBps")
    price_impact_percentage: str = Field(alias="priceImpactPct")
    route_plan: List[JupiterRoutePlanStep] = Field(alias="routePlan")


class JupiterSwapRequest(BaseModel):
    quote_response: JupiterQuoteResponse = Field(alias="quoteResponse")
    user_public_key: str = Field(alias="userPublicKey")
    wrap_and_unwrap_sol: bool = Field(default=True, alias="wrapAndUnwrapSol")
    use_shared_accounts: bool = Field(default=True, alias="useSharedAccounts")
    dynamic_compute_unit_limit: bool = Field(default=True, alias="dynamicComputeUnitLimit")
    skip_user_accounts_rpc_calls: bool = Field(default=True, alias="skipUserAccountsRpcCalls")


class JupiterSwapResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    swap_transaction: str = Field(alias="swapTransaction")
