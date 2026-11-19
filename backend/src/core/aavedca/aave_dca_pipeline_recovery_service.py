from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_helpers import (
    classify_aave_dca_pipeline_onchain_failure,
    find_pending_broadcast_operation,
    replace_broadcast_or_append_pipeline_operation,
)
from src.core.aavedca.aave_dca_notification_service import publish_dca_order_telegram_message
from src.core.aavedca.aave_dca_structures import (
    AaveDcaBlockingPipelineError,
    AaveDcaPipelineOnchainFailureRetryPolicy,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationDetails,
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
from src.integrations.aave.aave_structures import (
    AaveEvmTransactionBroadcast,
    AaveEvmTransactionConfirmationFailureKind,
    AaveEvmTransactionConfirmationOutcome,
)
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
            operation_details: AaveDcaPipelineOperationDetails,
            transaction_hash: Optional[str],
            nonce: Optional[int],
            failure_code: Optional[str],
            failure_message: Optional[str],
            pipeline_attempt_number: Optional[int],
    ) -> None:
        current_timestamp_iso: str = get_current_local_datetime().isoformat()
        pipeline_operation = AaveDcaPipelineOperation(
            step=pipeline_step,
            status=pipeline_status,
            started_at=current_timestamp_iso,
            completed_at=current_timestamp_iso,
            transaction_hash=transaction_hash,
            route_tool=operation_details.route_tool,
            source_amount_base_units=operation_details.source_amount_base_units,
            expected_output_base_units=operation_details.expected_output_base_units,
            minimum_output_base_units=operation_details.minimum_output_base_units,
            failure_code=failure_code,
            failure_message=failure_message,
            pipeline_attempt_number=pipeline_attempt_number,
            nonce=nonce,
            pre_swap_target_balance_base_units=operation_details.pre_swap_target_balance_base_units,
        )
        dca_order.pipeline_operations = replace_broadcast_or_append_pipeline_operation(
            dca_order.pipeline_operations,
            pipeline_operation,
        )

    def record_broadcast(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            transaction_broadcast: AaveEvmTransactionBroadcast,
            operation_details: AaveDcaPipelineOperationDetails,
    ) -> None:
        self.record_pipeline_operation(
            dca_order=dca_order,
            pipeline_step=pipeline_step,
            pipeline_status=AaveDcaPipelineOperationStatus.BROADCASTED,
            operation_details=operation_details,
            transaction_hash=transaction_broadcast.transaction_hash,
            nonce=transaction_broadcast.nonce,
            failure_code=None,
            failure_message=None,
            pipeline_attempt_number=dca_order.pipeline_attempt_count + 1,
        )
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        logger.info(
            "[AAVEDCA][RECOVERY][BROADCAST] Order_id=%s %s transaction %s recorded as broadcast with nonce=%s",
            dca_order.id,
            pipeline_step.value,
            transaction_broadcast.transaction_hash,
            transaction_broadcast.nonce,
        )

    def record_pre_broadcast_pipeline_failure(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            operation_details: AaveDcaPipelineOperationDetails,
            failure_code: Optional[str],
            failure_message: str,
    ) -> None:
        self.record_pipeline_operation(
            dca_order=dca_order,
            pipeline_step=pipeline_step,
            pipeline_status=AaveDcaPipelineOperationStatus.FAILED,
            operation_details=operation_details,
            transaction_hash=None,
            nonce=None,
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
            operation_details: AaveDcaPipelineOperationDetails,
    ) -> str:
        pending_broadcast_operation: Optional[AaveDcaPipelineOperation] = find_pending_broadcast_operation(
            dca_order.pipeline_operations,
            pipeline_step,
        )
        broadcast_nonce: Optional[int] = None
        if (
                pending_broadcast_operation is not None
                and pending_broadcast_operation.transaction_hash == confirmation_outcome.transaction_hash
        ):
            broadcast_nonce = pending_broadcast_operation.nonce

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
                operation_details=operation_details,
                transaction_hash=confirmation_outcome.transaction_hash,
                nonce=broadcast_nonce,
                failure_code=None,
                failure_message=None,
                pipeline_attempt_number=None,
            )
            return confirmation_outcome.transaction_hash

        failure_message: str = build_aave_dca_pipeline_step_failure_message(
            pipeline_step_label=pipeline_step_label,
            onchain_revert_reason=confirmation_outcome.onchain_revert_reason,
            confirmation_failure_kind=confirmation_outcome.confirmation_failure_kind,
        )
        if (
                confirmation_outcome.confirmation_failure_kind == AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT
                and broadcast_nonce is not None
        ):
            logger.info(
                "[AAVEDCA][RECOVERY][BROADCAST] Order_id=%s %s transaction %s still unconfirmed: it stays broadcast and is never sent again",
                dca_order.id,
                pipeline_step.value,
                confirmation_outcome.transaction_hash,
            )
            raise AaveDcaTransientPipelineError(failure_message)

        failure_classification = classify_aave_dca_pipeline_onchain_failure(
            confirmation_failure_kind=confirmation_outcome.confirmation_failure_kind,
            onchain_revert_reason=confirmation_outcome.onchain_revert_reason,
        )
        self.record_pipeline_operation(
            dca_order=dca_order,
            pipeline_step=pipeline_step,
            pipeline_status=AaveDcaPipelineOperationStatus.FAILED,
            operation_details=operation_details,
            transaction_hash=confirmation_outcome.transaction_hash,
            nonce=broadcast_nonce,
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
