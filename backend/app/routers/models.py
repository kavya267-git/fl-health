"""Model-registry endpoints. A model is identified by its modality: ehr, ecg or xray."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.routers.deps import current_user, get_ctx
from app.schemas.models import ModelDetail, ModelMetrics, ModelSummary
from app.services.context import AppContext
from app.services.views import model_detail, model_metrics
from ml.common.types import MODALITIES

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=List[ModelSummary])
def list_models(user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return [ctx.registry.describe(modality) for modality in MODALITIES]


@router.get("/{model_id}", response_model=ModelDetail)
def get_model(model_id: str, user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return model_detail(ctx, model_id)


@router.get("/{model_id}/metrics", response_model=ModelMetrics)
def get_model_metrics(model_id: str, user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return model_metrics(ctx, model_id)
