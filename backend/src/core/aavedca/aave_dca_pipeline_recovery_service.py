from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_helpers import (
    append_pipeline_operation,
    classify_aave_dca_pipeline_onchain_failure,
)
from src.core.aavedca.aave_dca_notification_service import publish_dca_order_telegram_message
from src.core.aavedca.aave_dca_structures import (
    AaveDcaBlockingPipelineError,
    AaveDcaPipelineOnchainFailureRetryPolicy,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaTransientPipelineError,
)
from src.core.aavedca.aave_dca_utils import (
    build_aave_dca_pipeline_step_failure_message,
    compute_pipeline_next_attempt_at,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_structures import AaveEvmTransactionConfirmationOutcome
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaPipelineRecoveryService:
    def __init__(self, database_session: Session, dca_order_dao: AaveDcaOrderDao) -> None:
        self.database_session = database_session
        self.dca_order_dao = dca_order_dao

    def reset_pipeline_recovery_state(self, dca_order: AaveDcaOrder) -> None:
        dca_order.pipeline_attempt_count = 0
        dca_order.next_attempt_at = None
        dca_order.suspension_reason = None

    def record_pipeline_operation(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            pipeline_status: AaveDcaPipelineOperationStatus,
            transaction_hash: Optional[str] = None,
            route_tool: Optional[str] = None,
            source_amount_base_units: Optional[int] = None,
            expected_output_base_units: Optional[int] = None,
            minimum_output_base_units: Optional[int] = None,
            failure_code: Optional[str] = None,
            failure_message: Optional[str] = None,
            pipeline_attempt_number: Optional[int] = None,
    ) -> None:
        current_timestamp_iso: str = get_current_local_datetime().isoformat()
        pipeline_operation = AaveDcaPipelineOperation(
            step=pipeline_step,
            status=pipeline_status,
            started_at=current_timestamp_iso,
            completed_at=current_timestamp_iso,
            transaction_hash=transaction_hash,
            route_tool=route_tool,
            source_amount_base_units=source_amount_base_units,
            expected_output_base_units=expected_output_base_units,
            minimum_output_base_units=minimum_output_base_units,
            failure_code=failure_code,
            failure_message=failure_message,
            pipeline_attempt_number=pipeline_attempt_number,
        )
        dca_order.pipeline_operations = append_pipeline_operation(
            dca_order.pipeline_operations,
            pipeline_operation,
        )

    def record_pre_broadcast_pipeline_failure(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            failure_message: str,
            route_tool: Optional[str] = None,
            source_amount_base_units: Optional[int] = None,
            expected_output_base_units: Optional[int] = None,
            minimum_output_base_units: Optional[int] = None,
            failure_code: Optional[str] = None,
    ) -> None:
        self.record_pipeline_operation(
            dca_order=dca_order,
            pipeline_step=pipeline_step,
            pipeline_status=AaveDcaPipelineOperationStatus.FAILED,
            route_tool=route_tool,
            source_amount_base_units=source_amount_base_units,
            expected_output_base_units=expected_output_base_units,
            minimum_output_base_units=minimum_output_base_units,
            failure_code=failure_code,
            failure_message=failure_message,
            pipeline_attempt_number=dca_order.pipeline_attempt_count + 1,
        )
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)

    def resolve_pipeline_step_onchain_outcome(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            pipeline_step_label: str,
            confirmation_outcome: AaveEvmTransactionConfirmationOutcome,
            route_tool: Optional[str] = None,
            source_amount_base_units: Optional[int] = None,
            expected_output_base_units: Optional[int] = None,
            minimum_output_base_units: Optional[int] = None,
    ) -> str:
        if confirmation_outcome.is_confirmed:
            if confirmation_outcome.transaction_hash is None:
                raise AaveDcaBlockingPipelineError(
                    AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                    f"{pipeline_step_label} transaction confirmed without transaction hash",
                )
            self.record_pipeline_operation(
                dca_order=dca_order,
                pipeline_step=pipeline_step,
                pipeline_status=AaveDcaPipelineOperationStatus.COMPLETED,
                transaction_hash=confirmation_outcome.transaction_hash,
                route_tool=route_tool,
                source_amount_base_units=source_amount_base_units,
                expected_output_base_units=expected_output_base_units,
                minimum_output_base_units=minimum_output_base_units,
            )
            return confirmation_outcome.transaction_hash

        failure_classification = classify_aave_dca_pipeline_onchain_failure(
            confirmation_failure_kind=confirmation_outcome.confirmation_failure_kind,
            onchain_revert_reason=confirmation_outcome.onchain_revert_reason,
        )
        failure_message: str = build_aave_dca_pipeline_step_failure_message(
            pipeline_step_label=pipeline_step_label,
            onchain_revert_reason=confirmation_outcome.onchain_revert_reason,
            confirmation_failure_kind=confirmation_outcome.confirmation_failure_kind,
        )
        self.record_pipeline_operation(
            dca_order=dca_order,
            pipeline_step=pipeline_step,
            pipeline_status=AaveDcaPipelineOperationStatus.FAILED,
            transaction_hash=confirmation_outcome.transaction_hash,
            route_tool=route_tool,
            source_amount_base_units=source_amount_base_units,
            expected_output_base_units=expected_output_base_units,
            minimum_output_base_units=minimum_output_base_units,
            failure_code=failure_classification.onchain_revert_reason,
            failure_message=failure_message,
            pipeline_attempt_number=dca_order.pipeline_attempt_count + 1,
        )
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)

        if failure_classification.retry_policy == AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING:
            raise AaveDcaBlockingPipelineError(
                failure_classification.suspension_reason.value,
                failure_message,
            )
        raise AaveDcaTransientPipelineError(failure_message)

    def suspend_order(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            suspension_reason: str,
    ) -> None:
        dca_order.suspension_reason = suspension_reason
        dca_order.next_attempt_at = None
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        logger.warning(
            "[AAVEDCA][RECOVERY][SUSPEND] Order_id=%s suspended at status=%s reason=%s",
            dca_order.id,
            dca_order.order_status,
            suspension_reason,
        )
        publish_dca_order_telegram_message(
            dca_order=dca_order,
            dca_strategy=dca_strategy,
            order_dao=self.dca_order_dao,
        )

    def schedule_transient_retry(
            self,
            dca_order: AaveDcaOrder,
            failure_message: str,
    ) -> None:
        dca_order.pipeline_attempt_count += 1
        if dca_order.pipeline_attempt_count > settings.AAVE_DCA_PIPELINE_MAX_RETRY_ATTEMPTS:
            logger.warning(
                "[AAVEDCA][RECOVERY][RETRY] Order_id=%s exceeded max retry attempts (%s): %s",
                dca_order.id,
                settings.AAVE_DCA_PIPELINE_MAX_RETRY_ATTEMPTS,
                failure_message,
            )
            raise AaveDcaBlockingPipelineError(
                AaveDcaPipelinePreflightFailureReason.MAX_RETRIES_EXCEEDED.value,
                failure_message,
            )

        dca_order.next_attempt_at = compute_pipeline_next_attempt_at(dca_order.pipeline_attempt_count)
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        logger.warning(
            "[AAVEDCA][RECOVERY][RETRY] Order_id=%s transient failure at status=%s attempt=%s next_attempt_at=%s message=%s",
            dca_order.id,
            dca_order.order_status,
            dca_order.pipeline_attempt_count,
            dca_order.next_attempt_at,
            failure_message,
        )

    def schedule_transient_retry_with_strategy(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            failure_message: str,
    ) -> None:
        self.schedule_transient_retry(dca_order, failure_message)
        publish_dca_order_telegram_message(
            dca_order=dca_order,
            dca_strategy=dca_strategy,
            order_dao=self.dca_order_dao,
        )
