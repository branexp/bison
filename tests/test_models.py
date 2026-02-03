from __future__ import annotations

import pytest
from pydantic import ValidationError

from emailbison.models import CampaignCreateSpec, LeadsSpec, SequenceSpec


def test_leads_exclusive() -> None:
    with pytest.raises(ValidationError):
        LeadsSpec(lead_list_id=1, lead_ids=[1, 2])


def test_campaign_create_requires_name() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateSpec.model_validate({})


def test_sequence_requires_steps() -> None:
    with pytest.raises(ValidationError):
        SequenceSpec.model_validate({"title": "x", "sequence_steps": []})
