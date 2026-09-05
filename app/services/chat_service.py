from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_guardrail, chat_prompts
from app.services.etfs import EtfNotFoundError, EtfReadService
from app.services.llm_client import LlmClient, get_llm_client

FALLBACK_MESSAGE = "답변을 가져오지 못했어요."
HISTORY_TURNS = 3


def handle_chat(
    session: Session,
    request: ChatRequest,
    llm_client: LlmClient | None = None,
) -> ChatResponse:
    context, compare_context, previous_product_name, all_products = _load_context(session, request)

    refusal = chat_guardrail.classify_refusal(request.message)
    if refusal is not None:
        return ChatResponse(message=refusal.message, refusal=True, action=refusal.action)

    system_prompt = chat_prompts.build_system_prompt(
        stage=request.stage,
        context=context,
        compare_context=compare_context,
        all_products=all_products,
        horizon=request.horizon,
        purpose=request.purpose,
        fund_nature=request.fundNature,
        previous_product_name=previous_product_name,
    )
    history = [
        {"role": turn.role, "content": turn.content} for turn in request.history[-HISTORY_TURNS:]
    ]

    client = llm_client or get_llm_client()
    try:
        answer = client.ask(system_prompt, history, request.message)
    except Exception:
        return ChatResponse(message=FALLBACK_MESSAGE, refusal=False, action="RETRY")

    banned = chat_guardrail.find_banned_phrase(answer.message)
    message = chat_guardrail.NEUTRAL_OVERRIDE_MESSAGE if banned is not None else answer.message

    return ChatResponse(message=message, refusal=answer.refusal, action=answer.action)


def _load_context(
    session: Session, request: ChatRequest
) -> tuple[dict, dict | None, str | None, list[dict]]:
    service = EtfReadService(session)
    context = service.get_etf_context(
        code=request.productCode,
        horizon=request.horizon,
        purpose=request.purpose,
        fund_nature=request.fundNature,
    )
    compare_context = _try_get_context(service, request)
    previous_product_name = _try_get_name(service, request.previousProductCode)
    all_products = service.list_etf_summaries()
    return context, compare_context, previous_product_name, all_products


def _try_get_context(service: EtfReadService, request: ChatRequest) -> dict | None:
    if not request.compareProductCode:
        return None
    try:
        return service.get_etf_context(
            code=request.compareProductCode,
            horizon=request.horizon,
            purpose=request.purpose,
            fund_nature=request.fundNature,
        )
    except EtfNotFoundError:
        return None


def _try_get_name(service: EtfReadService, code: str | None) -> str | None:
    if not code:
        return None
    try:
        return service.get_etf_detail(code)["name"]
    except EtfNotFoundError:
        return None
