"""Validated API contracts used by the Quetzal frontend."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Country = Literal["PA", "MX", "CO", "BR", "AR", "CL", "PE", "EC", "CR", "GT", "DO", "UY"]
CountryFilter = Literal["ALL", "PA", "MX", "CO", "BR", "AR", "CL", "PE", "EC", "CR", "GT", "DO", "UY"]
GenieSpace = Literal["ingresos", "clientes", "red"]
VoiceTheme = Literal["NETWORK_QUALITY", "BILLING", "SERVICE", "PLAN_VALUE", "OTHER"]
CampaignObjective = Literal["RETENTION", "CROSS_SELL"]
CampaignChannel = Literal["EMAIL", "SMS", "WHATSAPP", "CALL"]
CampaignWorkflowStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "CANCELLED"]
RetentionPriority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RetentionStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "IN_PROGRESS", "RESOLVED", "CLOSED"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportRequest(StrictRequest):
    country: CountryFilter = "ALL"


class GenieQueryRequest(StrictRequest):
    space: GenieSpace = "ingresos"
    question: str = Field(min_length=2, max_length=4000)
    deep: bool = False
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("question must contain at least two non-space characters")
        return value


class ChatHistoryTurn(StrictRequest):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=12000)
    tools: list[Literal["web_search", "telecom_snapshot", "ontobricks_semantic_query"]] = Field(default_factory=list, max_length=8)


class ChatRequest(StrictRequest):
    message: str = Field(min_length=2, max_length=4000)
    disable_tools: bool = False
    conversation_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    history: list[ChatHistoryTurn] = Field(default_factory=list, max_length=30)
    continuation_mode: Literal["auto", "external", "internal"] = "auto"

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("message must contain at least two non-space characters")
        return value


IncidentStatus = Literal["NEW", "ACKNOWLEDGED", "IN_PROGRESS", "MONITORING", "RESOLVED"]
ActionType = Literal["DISPATCH_FIELD", "CREATE_WORK_ORDER", "CUSTOMER_NOTICE", "RETENTION_CAMPAIGN", "COMPENSATION", "CAPACITY_CHANGE"]
ActionDecision = Literal["APPROVED", "REJECTED"]
RecommendationDecision = Literal["ACCEPTED", "REJECTED"]
RecommendationOutcome = Literal["EXECUTED", "CONVERTED", "NO_OUTCOME"]
AlertDomain = Literal["NETWORK", "CUSTOMER", "REVENUE", "BILLING"]
AlertOperator = Literal[">", ">=", "<", "<=", "="]
AlertChannel = Literal["IN_APP", "EMAIL", "WEBHOOK"]


class IncidentUpdateRequest(StrictRequest):
    status: IncidentStatus
    assignee: str | None = Field(default=None, max_length=120)


class ActionCreateRequest(StrictRequest):
    action_type: ActionType
    rationale: str = Field(min_length=5, max_length=1000)


class ActionDecisionRequest(StrictRequest):
    decision: ActionDecision
    note: str = Field(default="", max_length=1000)


class ActionExecutionRequest(StrictRequest):
    connector: Literal["AUTO", "INTERNAL", "CRM", "OSS", "BSS"] = "AUTO"
    note: str = Field(default="", max_length=1000)


class RecommendationDecisionRequest(StrictRequest):
    recommendation_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    title: str = Field(min_length=3, max_length=240)
    reason: str = Field(min_length=3, max_length=1000)
    decision: RecommendationDecision
    product_id: str | None = Field(default=None, max_length=128)
    score: float | None = Field(default=None, ge=0, le=100)
    note: str = Field(default="", max_length=1000)


class RecommendationOutcomeRequest(StrictRequest):
    outcome: RecommendationOutcome
    outcome_value_usd: float | None = Field(default=None, ge=0, le=100000000)
    note: str = Field(default="", max_length=1000)


class RetentionCaseCreateRequest(StrictRequest):
    """Create a governed operational case from an explainable recommendation."""

    recommendation_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    title: str = Field(min_length=3, max_length=240)
    rationale: str = Field(min_length=5, max_length=2000)
    priority: RetentionPriority
    source_recommendation_id: str | None = Field(default=None, max_length=128)
    assignee: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=1000)


class RetentionCaseTransitionRequest(StrictRequest):
    """Advance a case using optimistic concurrency; actors come from trusted headers."""

    to_status: RetentionStatus
    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=2000)


class ScenarioRequest(StrictRequest):
    country: CountryFilter = "ALL"
    growth_pct: float = Field(ge=-30, le=200)
    horizon_days: int = Field(default=90, ge=7, le=730)
    traffic_shift_pct: float = Field(default=0, ge=-50, le=50)


class FinancialImpactRequest(StrictRequest):
    """Governed assumptions for a counterfactual retention estimate."""

    country: CountryFilter = "ALL"
    treated_customers: int = Field(default=1000, ge=1, le=1_000_000)
    relative_churn_reduction_pct: float = Field(default=15, ge=0, le=100)
    cost_per_contact_usd: float = Field(default=8, ge=0, le=100_000)
    horizon_months: int = Field(default=12, ge=1, le=36)


class CampaignOptimizeRequest(StrictRequest):
    """Bounded assumptions for a deterministic, non-executing campaign draft."""

    country: CountryFilter = "ALL"
    objective: CampaignObjective = "RETENTION"
    channel: CampaignChannel = "EMAIL"
    source_theme_id: VoiceTheme | None = None
    budget_usd: float = Field(default=5000, gt=0, le=10_000_000)
    cost_per_contact_usd: float = Field(default=2, gt=0, le=100_000)
    max_customers: int = Field(default=1000, ge=1, le=10_000)
    contact_capacity: int = Field(default=500, ge=1, le=10_000)
    expected_response_rate_pct: float = Field(default=8, ge=0, le=100)
    horizon_months: int = Field(default=12, ge=1, le=36)


class CampaignDraftCreateRequest(StrictRequest):
    """Persist a freshly recomputed governed campaign snapshot in Lakebase."""

    title: str = Field(min_length=3, max_length=160)
    assigned_to: str | None = Field(
        default=None, min_length=3, max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9@._+\-]{1,199}$",
    )
    campaign: CampaignOptimizeRequest


class CampaignDraftRevisionRequest(StrictRequest):
    """Create an immutable new audience/economic version of a saved draft."""

    expected_version: int = Field(ge=1)
    campaign: CampaignOptimizeRequest
    title: str | None = Field(default=None, min_length=3, max_length=160)
    assigned_to: str | None = Field(
        default=None, min_length=3, max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9@._+\-]{1,199}$",
    )
    note: str = Field(default="", max_length=2000)


class CampaignDraftTransitionRequest(StrictRequest):
    """Advance a saved campaign using optimistic concurrency."""

    to_status: CampaignWorkflowStatus
    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=2000)


class AlertSubscriptionRequest(StrictRequest):
    name: str = Field(min_length=3, max_length=120)
    domain: AlertDomain
    country: CountryFilter = "ALL"
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    operator: AlertOperator
    threshold: float
    channel: AlertChannel = "IN_APP"
    enabled: bool = True


class AlertStateRequest(StrictRequest):
    enabled: bool


class AlertAcknowledgeRequest(StrictRequest):
    note: str = Field(default="", max_length=1000)
