from collections.abc import Generator

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.schemas.etfs import (
    BatchDiagnosisResponse,
    DiagnosisResponse,
    EtfContextResponse,
    EtfDetailResponse,
    EtfListResponse,
)
from app.db.session import get_db
from app.domain.enums import FundNature, Horizon, Purpose
from app.services.etfs import EtfNotFoundError, EtfReadService

router = APIRouter(prefix="/v1/etfs", tags=["etfs"])
DB_DEPENDENCY = Depends(get_db)


def get_etf_service(db: Session = DB_DEPENDENCY) -> Generator[EtfReadService]:
    yield EtfReadService(db)


ETF_SERVICE_DEPENDENCY = Depends(get_etf_service)


@router.get("", response_model=EtfListResponse)
def list_etfs(
    q: str | None = Query(default=None),
    service: EtfReadService = ETF_SERVICE_DEPENDENCY,
) -> dict:
    return service.list_etfs(q=q)


@router.get(
    "/diagnosis/batch",
    response_model=BatchDiagnosisResponse,
    response_model_exclude_none=True,
)
def get_batch_diagnosis(
    codes: str | None = Query(default=None),
    horizon: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
    fund_nature: str | None = Query(default=None),
    service: EtfReadService = ETF_SERVICE_DEPENDENCY,
):
    parsed_codes = _parse_codes(codes)
    if isinstance(parsed_codes, JSONResponse):
        return parsed_codes
    parsed_horizon = _parse_required_enum("horizon", horizon, Horizon)
    if isinstance(parsed_horizon, JSONResponse):
        return parsed_horizon
    parsed_purpose = _parse_required_enum("purpose", purpose, Purpose)
    if isinstance(parsed_purpose, JSONResponse):
        return parsed_purpose
    parsed_fund_nature = _parse_required_enum("fund_nature", fund_nature, FundNature)
    if isinstance(parsed_fund_nature, JSONResponse):
        return parsed_fund_nature

    try:
        return service.get_batch_diagnosis(
            codes=parsed_codes,
            horizon=parsed_horizon,
            purpose=parsed_purpose,
        )
    except EtfNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, "ETF_NOT_FOUND", "ETF를 찾을 수 없습니다.")


@router.get("/{code}", response_model=EtfDetailResponse)
def get_etf(
    code: str,
    service: EtfReadService = ETF_SERVICE_DEPENDENCY,
):
    try:
        return service.get_etf_detail(code)
    except EtfNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, "ETF_NOT_FOUND", "ETF를 찾을 수 없습니다.")


@router.get("/{code}/diagnosis", response_model=DiagnosisResponse)
def get_etf_diagnosis(
    code: str,
    horizon: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
    fund_nature: str | None = Query(default=None),
    service: EtfReadService = ETF_SERVICE_DEPENDENCY,
):
    parsed_horizon = _parse_required_enum("horizon", horizon, Horizon)
    if isinstance(parsed_horizon, JSONResponse):
        return parsed_horizon
    parsed_purpose = _parse_required_enum("purpose", purpose, Purpose)
    if isinstance(parsed_purpose, JSONResponse):
        return parsed_purpose
    parsed_fund_nature = _parse_required_enum("fund_nature", fund_nature, FundNature)
    if isinstance(parsed_fund_nature, JSONResponse):
        return parsed_fund_nature

    try:
        return service.get_etf_diagnosis(
            code=code,
            horizon=parsed_horizon,
            purpose=parsed_purpose,
            fund_nature=parsed_fund_nature,
        )
    except EtfNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, "ETF_NOT_FOUND", "ETF를 찾을 수 없습니다.")


@router.get("/{code}/context", response_model=EtfContextResponse)
def get_etf_context(
    code: str,
    horizon: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
    fund_nature: str | None = Query(default=None),
    service: EtfReadService = ETF_SERVICE_DEPENDENCY,
):
    parsed_horizon = _parse_required_enum("horizon", horizon, Horizon)
    if isinstance(parsed_horizon, JSONResponse):
        return parsed_horizon
    parsed_purpose = _parse_required_enum("purpose", purpose, Purpose)
    if isinstance(parsed_purpose, JSONResponse):
        return parsed_purpose
    parsed_fund_nature = _parse_required_enum("fund_nature", fund_nature, FundNature)
    if isinstance(parsed_fund_nature, JSONResponse):
        return parsed_fund_nature

    try:
        return service.get_etf_context(
            code=code,
            horizon=parsed_horizon,
            purpose=parsed_purpose,
            fund_nature=parsed_fund_nature,
        )
    except EtfNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, "ETF_NOT_FOUND", "ETF를 찾을 수 없습니다.")


def _parse_codes(value: str | None) -> list[str] | JSONResponse:
    if value is None:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "MISSING_PARAMETER",
            "codes 값이 필요합니다.",
            "codes",
        )
    codes = [code.strip() for code in value.split(",") if code.strip()]
    if not codes:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "MISSING_PARAMETER",
            "codes 값이 필요합니다.",
            "codes",
        )
    if len(codes) > 8:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "TOO_MANY_CODES",
            "codes는 최대 8개까지 가능합니다.",
            "codes",
        )
    return codes


def _parse_required_enum(field: str, value: str | None, enum_type: type) -> object | JSONResponse:
    if value is None:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "MISSING_PARAMETER",
            f"{field} 값이 필요합니다.",
            field,
        )
    try:
        return enum_type(value)
    except ValueError:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PARAMETER",
            f"{field} 값이 올바르지 않습니다.",
            field,
        )


def _error(status_code: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "field": field}}
    return JSONResponse(status_code=status_code, content=body)
