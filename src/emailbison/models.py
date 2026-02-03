from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CampaignType = Literal["outbound", "reply_followup"]


class CampaignSettings(BaseModel):
    """Maps to PATCH /api/campaigns/{id}/update"""

    name: str | None = None
    max_emails_per_day: int | None = None
    max_new_leads_per_day: int | None = None

    plain_text: bool | None = None
    open_tracking: bool | None = None
    reputation_building: bool | None = None

    can_unsubscribe: bool | None = None
    unsubscribe_text: str | None = None

    include_auto_replies_in_stats: bool | None = None


class CampaignSchedule(BaseModel):
    """Maps to POST/PUT /api/campaigns/{campaign_id}/schedule"""

    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True
    saturday: bool = False
    sunday: bool = False

    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str

    save_as_template: bool = False


class SequenceStep(BaseModel):
    email_subject: str = Field(min_length=1)
    email_subject_variables: list[str] | None = None

    order: int | None = None
    email_body: str = Field(min_length=1)
    wait_in_days: int = Field(ge=0)

    variant: bool | None = None
    variant_from_step: int | None = None
    variant_from_step_id: int | None = None

    thread_reply: bool | None = None

    @model_validator(mode="after")
    def _validate_variant(self) -> SequenceStep:
        if self.variant_from_step is not None and self.variant_from_step_id is not None:
            raise ValueError("Use only one of variant_from_step or variant_from_step_id")
        return self


class SequenceSpec(BaseModel):
    title: str = Field(min_length=1)
    sequence_steps: list[SequenceStep] = Field(min_length=1)


class LeadsSpec(BaseModel):
    lead_list_id: int | None = None
    lead_ids: list[int] | None = None
    allow_parallel_sending: bool = False

    @model_validator(mode="after")
    def _validate_exclusive(self) -> LeadsSpec:
        if self.lead_list_id is not None and self.lead_ids is not None:
            raise ValueError("Use only one of lead_list_id or lead_ids")
        return self


class CampaignCreateSpec(BaseModel):
    """Locally-validated input model for v1 campaign creation.

    This is a *workflow spec* that orchestrates multiple EmailBison endpoints:
    - POST /api/campaigns
    - PATCH /api/campaigns/{id}/update (optional)
    - POST /api/campaigns/{id}/schedule (optional)
    - POST /api/campaigns/v1.1/{id}/sequence-steps (optional)
    - POST /api/campaigns/{id}/attach-sender-emails (optional)
    - POST /api/campaigns/{id}/leads/attach-* (optional)

    File-driven mode should use this schema.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: CampaignType = "outbound"

    settings: CampaignSettings | None = None
    schedule: CampaignSchedule | None = None
    sequence: SequenceSpec | None = None

    # Attach sender email accounts to the campaign. Repeatable.
    sender_email_ids: list[int] | None = Field(default=None, min_length=1)

    leads: LeadsSpec | None = None


class CreateCampaignResult(BaseModel):
    id: int
    name: str
    status: str | None = None

    # Optional extra details
    raw: dict | None = None
