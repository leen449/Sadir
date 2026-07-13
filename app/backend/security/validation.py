"""
validation.py

Validates every LLM request before Azure OpenAI is ever called.

Checks performed (per specification section 15):
    1. transaction ID exists
    2. selected node exists
    3. question ID is supported (only when request_type == "question")
    4. selected node refers to the same transaction under investigation

If any check fails, request is rejected with a ValidationError carrying a
machine-readable reason code -- never a silent failure, never a raw
exception leaking artifact/internal details to the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.backend.services import artifact_service
from app.backend.services.transaction_service import SelectedNode

# Fixed, closed set of supported question IDs. The frontend may only ever
# send one of these -- never raw prompt text (spec section 20).
SUPPORTED_QUESTION_IDS = {"question_1", "question_2", "question_3"}
SUPPORTED_REQUEST_TYPES = {"initial_analysis", "question"}


@dataclass(frozen=True)
class ValidationError(Exception):
    """Raised when a request fails validation. Carries a stable reason_code
    so callers/tests can assert on *why* a request was rejected without
    parsing free-text messages."""

    reason_code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.reason_code}] {self.message}"


def validate_transaction_exists(transaction_id: str) -> None:
    if not transaction_id or not artifact_service.transaction_exists(transaction_id):
        raise ValidationError(
            reason_code="TRANSACTION_NOT_FOUND",
            message=f"Transaction ID {transaction_id!r} does not exist.",
        )


def validate_selected_node_exists(selected_node: Optional[SelectedNode]) -> None:
    if selected_node is None:
        raise ValidationError(
            reason_code="SELECTED_NODE_MISSING",
            message="No selected node was supplied with the request.",
        )
    if not artifact_service.node_exists(selected_node.node_index):
        raise ValidationError(
            reason_code="SELECTED_NODE_NOT_FOUND",
            message=f"Selected node {selected_node.node_index!r} does not exist.",
        )


def validate_question_id(request_type: str, question_id: Optional[str]) -> None:
    if request_type not in SUPPORTED_REQUEST_TYPES:
        raise ValidationError(
            reason_code="UNSUPPORTED_REQUEST_TYPE",
            message=f"Request type {request_type!r} is not supported.",
        )
    if request_type == "question":
        if question_id not in SUPPORTED_QUESTION_IDS:
            raise ValidationError(
                reason_code="UNSUPPORTED_QUESTION_ID",
                message=f"Question ID {question_id!r} is not supported.",
            )


def validate_node_matches_transaction(transaction_id: str, selected_node: SelectedNode) -> None:
    """The selected node must refer to the same transaction under
    investigation -- i.e. it is the target transaction's own node, not an
    unrelated one. Neighbor/edge evidence is handled separately as context,
    not as the subject of the request."""
    if str(selected_node.txId) != str(transaction_id):
        raise ValidationError(
            reason_code="NODE_TRANSACTION_MISMATCH",
            message=(
                f"Selected node txId {selected_node.txId!r} does not match "
                f"requested transaction_id {transaction_id!r}."
            ),
        )


def validate_request(
    transaction_id: str,
    selected_node: Optional[SelectedNode],
    request_type: str,
    question_id: Optional[str] = None,
) -> None:
    """
    Run all validation checks in order. Raises ValidationError on the first
    failure. Must be called before any TransactionContext is used to call
    Azure OpenAI.
    """
    validate_transaction_exists(transaction_id)
    validate_selected_node_exists(selected_node)
    validate_node_matches_transaction(transaction_id, selected_node)
    validate_question_id(request_type, question_id)
