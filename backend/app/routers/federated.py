"""Federated-learning endpoints.

Two audiences:

* signed-in users (dashboard) - start rounds, watch progress, trigger aggregation;
* hospital nodes - join a round, download the global model, upload an update,
  report an evaluation. These authenticate with ``X-Hospital-Token``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from analytics.privacy.dp import DPConfig
from app.routers.deps import coordinator_user, get_ctx, is_hospital_operator, permitted, verify_node
from app.schemas.federated import (
    DataCheckReport,
    EvaluationAccepted,
    EvaluationRequest,
    FailureRequest,
    FinalizeRequest,
    HeartbeatAccepted,
    HeartbeatRequest,
    NodePendingRounds,
    NodeRoundInfo,
    ParticipateRequest,
    Round,
    RoundDetail,
    RoundMetrics,
    StartRoundRequest,
    UpdateAccepted,
)
from app.services.context import AppContext
from app.services.views import round_detail, sanitize_data_summary
from app.utils.errors import NotFoundError, PermissionDenied, ValidationFailed

router = APIRouter(prefix="/api/federated", tags=["federated learning"])


# ------------------------------------------------------------------ dashboard
@router.post("/rounds/start", response_model=RoundDetail, status_code=201)
def start_round(
    body: StartRoundRequest, user: Dict[str, Any] = Depends(coordinator_user), ctx: AppContext = Depends(get_ctx)
):
    """Create a round and open it for hospitals.

    The response confirms the round exists; training then proceeds in the
    background. Poll ``GET /rounds/{id}`` for progress.
    """
    hospitals = ctx.hospitals.list_raw()
    if body.hospital_ids is not None:
        known = {h["id"] for h in hospitals}
        unknown = sorted(set(body.hospital_ids) - known)
        if unknown:
            raise NotFoundError(f"Unknown hospital id(s): {', '.join(unknown)}")
        hospitals = [h for h in hospitals if h["id"] in set(body.hospital_ids)]
    created = ctx.coordinator.start_round(
        body.modality,
        hospitals,
        actor=user["email"],
        local_epochs=body.local_epochs,
        batch_size=body.batch_size,
        learning_rate=body.learning_rate,
        min_participants=body.min_participants,
        auto_aggregate=body.auto_aggregate,
        dp=DPConfig(**body.differential_privacy.model_dump()),
        is_simulated=ctx.settings.demo_mode,
        deadline_seconds=body.deadline_seconds,
        simulated_missing_rate=body.simulated_missing_rate,
    )
    if ctx.nodes is not None:
        ctx.nodes.submit(created["id"])
    return round_detail(ctx, created["id"])


@router.get("/rounds", response_model=List[Round])
def list_rounds(
    modality: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: Dict[str, Any] = Depends(permitted("rounds_read")),
    ctx: AppContext = Depends(get_ctx),
):
    return ctx.coordinator.list_rounds(modality, limit)


@router.get("/rounds/{round_id}", response_model=RoundDetail)
def get_round(round_id: str, user: Dict[str, Any] = Depends(permitted("rounds_read")), ctx: AppContext = Depends(get_ctx)):
    return round_detail(ctx, round_id, viewer=user)


@router.get("/rounds/{round_id}/metrics", response_model=RoundMetrics)
def get_round_metrics(round_id: str, user: Dict[str, Any] = Depends(permitted("rounds_read")), ctx: AppContext = Depends(get_ctx)):
    metrics = ctx.coordinator.round_metrics(round_id)
    if is_hospital_operator(user):
        # Per-hospital figures of other hospitals are theirs; an operator sees its own and the global ones.
        own = user.get("hospital_id")
        metrics["local"] = [m for m in metrics["local"] if m["hospital_id"] == own]
        metrics["global_per_hospital"] = [m for m in metrics["global_per_hospital"] if m["hospital_id"] == own]
    return metrics


@router.post("/rounds/{round_id}/aggregate", response_model=RoundDetail)
def aggregate_round(
    round_id: str, user: Dict[str, Any] = Depends(coordinator_user), ctx: AppContext = Depends(get_ctx)
):
    """Run FedAvg now on the updates received so far (hospitals that have not reported are dropped)."""
    ctx.coordinator.aggregate(round_id, user["email"])
    return round_detail(ctx, round_id)


@router.post("/rounds/{round_id}/finalize", response_model=RoundDetail)
def finalize_round(
    round_id: str,
    body: FinalizeRequest,
    user: Dict[str, Any] = Depends(coordinator_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Complete an evaluating round with the evaluation reports received so far."""
    ctx.coordinator.finalize(round_id, user["email"], allow_partial=body.allow_partial)
    return round_detail(ctx, round_id)


@router.post("/rounds/{round_id}/cancel", response_model=RoundDetail)
def cancel_round(round_id: str, user: Dict[str, Any] = Depends(coordinator_user), ctx: AppContext = Depends(get_ctx)):
    """Stop a round that is stuck. It is recorded as failed."""
    ctx.coordinator.fail_round(round_id, f"Cancelled by {user['email']}.", actor=user["email"])
    return round_detail(ctx, round_id)


# ------------------------------------------------------------ hospital nodes
@router.post("/node/heartbeat", response_model=HeartbeatAccepted)
def node_heartbeat(body: HeartbeatRequest, request: Request, ctx: AppContext = Depends(get_ctx)):
    """Sent by each external node every ~10 s. A hospital is online while these keep arriving."""
    verify_node(request, ctx, body.hospital_id)
    beat = body.model_dump()
    beat["data_summary"] = sanitize_data_summary(body.data_summary)
    return ctx.hospitals.record_heartbeat(body.hospital_id, beat)


@router.get("/node/whoami")
def node_whoami(request: Request, ctx: AppContext = Depends(get_ctx)):
    """Which registered hospital a node token belongs to. 403 for an unknown or revoked token."""
    hospital_id = ctx.hospitals.hospital_for_token(request.headers.get("x-hospital-token", ""))
    if hospital_id is None:
        raise PermissionDenied("This node token is not valid. Generate a new one on the 'My hospital' page.")
    return ctx.hospitals.node_profile(hospital_id)


@router.get("/node/profile")
def node_profile(request: Request, hospital_id: str = Query(...), ctx: AppContext = Depends(get_ctx)):
    """Name and declared modalities, for setup_hospital.py on the hospital's machine."""
    verify_node(request, ctx, hospital_id)
    return ctx.hospitals.node_profile(hospital_id)


@router.post("/node/data-check")
def node_data_check(body: DataCheckReport, request: Request, ctx: AppContext = Depends(get_ctx)):
    """The node's LOCAL data check: pass / fail, counts and short problem notes per modality. No records."""
    verify_node(request, ctx, body.hospital_id)
    return ctx.hospitals.record_data_check(body.hospital_id, body.modalities)


@router.get("/node/rounds", response_model=NodePendingRounds)
def node_pending_rounds(request: Request, hospital_id: str = Query(...), ctx: AppContext = Depends(get_ctx)):
    """Rounds this hospital is invited to and has not joined yet (polled by external nodes)."""
    verify_node(request, ctx, hospital_id)
    return {
        "hospital_id": hospital_id,
        "round_ids": ctx.coordinator.pending_rounds_for(hospital_id),
        "participating": ctx.hospitals.get_raw(hospital_id)["participating"],
    }


@router.post("/rounds/{round_id}/participate", response_model=NodeRoundInfo)
def participate(round_id: str, body: ParticipateRequest, request: Request, ctx: AppContext = Depends(get_ctx)):
    verify_node(request, ctx, body.hospital_id)
    return ctx.coordinator.join(round_id, body.hospital_id, sanitize_data_summary(body.data_summary))


@router.get("/rounds/{round_id}/global-model")
def download_global_model(
    round_id: str,
    request: Request,
    hospital_id: str = Query(...),
    which: str = Query(default="base"),
    ctx: AppContext = Depends(get_ctx),
):
    """Weights as an .npz archive: the round's base model, or the aggregated result for evaluation."""
    verify_node(request, ctx, hospital_id)
    payload = ctx.coordinator.global_model_bytes(round_id, hospital_id, which)
    return Response(content=payload, media_type="application/octet-stream")


@router.post("/rounds/{round_id}/updates", response_model=UpdateAccepted)
async def submit_update(
    round_id: str,
    request: Request,
    hospital_id: str = Form(...),
    num_samples: int = Form(...),
    metrics: str = Form(default="{}"),
    dp_report: str = Form(default="{}"),
    architecture_signature: Optional[str] = Form(default=None),
    weights: UploadFile = File(...),
    ctx: AppContext = Depends(get_ctx),
):
    """Upload one hospital's model update: weights plus sample count and summary metrics."""
    verify_node(request, ctx, hospital_id)
    try:
        metrics_payload = json.loads(metrics)
        dp_payload = json.loads(dp_report)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(f"'metrics' and 'dp_report' must be JSON: {exc}") from exc
    if not isinstance(metrics_payload, dict) or not isinstance(dp_payload, dict):
        raise ValidationFailed("'metrics' and 'dp_report' must be JSON objects")
    payload = await weights.read(ctx.settings.max_update_bytes + 1)
    # Validation and (possibly) aggregation are CPU-bound; keep them off the event loop.
    return await run_in_threadpool(
        ctx.coordinator.receive_update,
        round_id,
        hospital_id,
        payload,
        num_samples,
        metrics_payload,
        dp_payload,
        architecture_signature,
    )


@router.post("/rounds/{round_id}/evaluations", response_model=EvaluationAccepted)
def submit_evaluation(round_id: str, body: EvaluationRequest, request: Request, ctx: AppContext = Depends(get_ctx)):
    verify_node(request, ctx, body.hospital_id)
    return ctx.coordinator.receive_evaluation(round_id, body.hospital_id, body.evaluation, body.explanation)


@router.post("/rounds/{round_id}/failures", status_code=204)
def report_failure(round_id: str, body: FailureRequest, request: Request, ctx: AppContext = Depends(get_ctx)):
    verify_node(request, ctx, body.hospital_id)
    ctx.coordinator.report_failure(round_id, body.hospital_id, body.stage, body.message)
    return Response(status_code=204)


@router.get("/rounds/{round_id}/node-status", response_model=NodeRoundInfo)
def node_status(round_id: str, request: Request, hospital_id: str = Query(...), ctx: AppContext = Depends(get_ctx)):
    """Lets a node poll for the round's status between training and evaluation."""
    verify_node(request, ctx, hospital_id)
    return ctx.coordinator.node_round_info(round_id)
