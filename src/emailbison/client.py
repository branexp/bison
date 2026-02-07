from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .utils.redact import redact_token


class EmailBisonError(RuntimeError):
    pass


class AuthError(EmailBisonError):
    pass


class ApiError(EmailBisonError):
    def __init__(self, message: str, *, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class NetworkError(EmailBisonError):
    pass


@dataclass(frozen=True)
class DebugInfo:
    method: str
    url: str
    status_code: int | None
    request_id: str | None


class EmailBisonClient:
    def __init__(self, settings: Settings, *, debug: bool = False):
        self.settings = settings
        self.debug = debug
        self._client = httpx.Client(
            base_url=self.settings.base_url,
            timeout=httpx.Timeout(self.settings.timeout_seconds),
            headers={
                "Authorization": f"Bearer {self.settings.api_token}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def debug_redacted_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {redact_token(self.settings.api_token)}",
        }

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], DebugInfo]:
        url = f"{self.settings.base_url}{path}" if path.startswith("/") else path
        resp: httpx.Response | None = None
        request_kwargs: dict[str, Any] = {}
        if params:
            request_kwargs["params"] = params

        try:
            if json_body is None:
                resp = self._client.request(method, path, **request_kwargs)
            else:
                headers = {"Content-Type": "application/json"}
                resp = self._client.request(
                    method,
                    path,
                    content=json.dumps(json_body),
                    headers=headers,
                    **request_kwargs,
                )
        except httpx.TimeoutException as e:
            raise NetworkError("Network timeout calling EmailBison") from e
        except httpx.HTTPError as e:
            raise NetworkError("Network error calling EmailBison") from e

        dbg = self._debug_summary(resp, method=method.upper(), url=url)
        self._raise_for_status(resp)
        return _safe_json(resp), dbg

    def _debug_summary(
        self,
        resp: httpx.Response | None,
        *,
        method: str,
        url: str,
    ) -> DebugInfo:
        request_id = None
        status = None
        if resp is not None:
            status = resp.status_code
            request_id = resp.headers.get("x-request-id") or resp.headers.get("x-correlation-id")
        return DebugInfo(method=method, url=url, status_code=status, request_id=request_id)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise AuthError("Auth failed (401/403). Set EMAILBISON_API_TOKEN or config api_token.")
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            msg = "Rate limited (429)."
            if retry_after:
                msg += f" Retry-After: {retry_after}"
            raise ApiError(msg, status_code=resp.status_code, details=_safe_json(resp))
        if resp.status_code >= 400:
            raise ApiError(
                f"API error ({resp.status_code}).",
                status_code=resp.status_code,
                details=_safe_json(resp),
            )

    # High-level helpers

    def create_campaign(
        self,
        *,
        name: str,
        type: str = "outbound",
    ) -> tuple[dict[str, Any], DebugInfo]:
        payload: dict[str, Any] = {"name": name, "type": type}
        return self.request_json("POST", self.settings.campaigns_path, json_body=payload)

    def update_campaign_settings(
        self,
        campaign_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/update"
        return self.request_json("PATCH", path, json_body=payload)

    def create_campaign_schedule(
        self,
        campaign_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/schedule"
        return self.request_json("POST", path, json_body=payload)

    def get_sequence_steps_v11(
        self,
        campaign_id: int,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_v11_path}/{campaign_id}/sequence-steps"
        return self.request_json("GET", path)

    def create_sequence_steps_v11(
        self,
        campaign_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_v11_path}/{campaign_id}/sequence-steps"
        return self.request_json("POST", path, json_body=payload)

    def update_sequence_steps_v11(
        self,
        sequence_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_v11_path}/sequence-steps/{sequence_id}"
        return self.request_json("PUT", path, json_body=payload)

    def delete_sequence_step(
        self,
        sequence_step_id: int,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"/api/campaigns/sequence-steps/{sequence_step_id}"
        return self.request_json("DELETE", path)

    def test_sequence_step_email(
        self,
        sequence_step_id: int,
        *,
        email: str,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"/api/campaigns/sequence-steps/{sequence_step_id}/test-email"
        return self.request_json("POST", path, json_body={"email": email})

    def attach_lead_list(
        self,
        campaign_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/leads/attach-lead-list"
        return self.request_json("POST", path, json_body=payload)

    def attach_leads(
        self,
        campaign_id: int,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/leads/attach-leads"
        return self.request_json("POST", path, json_body=payload)

    def list_campaigns(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        tag_ids: list[int] | None = None,
    ) -> tuple[dict[str, Any], DebugInfo]:
        payload: dict[str, Any] = {}
        if search:
            payload["search"] = search
        if status:
            payload["status"] = status
        if tag_ids:
            payload["tag_ids"] = tag_ids

        # Docs show optional requestBody for GET (unusual, but supported by EmailBison).
        return self.request_json(
            "GET",
            self.settings.campaigns_path,
            json_body=payload or None,
        )

    def get_campaign_sender_emails(
        self,
        campaign_id: int,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/sender-emails"
        return self.request_json("GET", path)

    def attach_sender_emails(
        self,
        campaign_id: int,
        *,
        sender_email_ids: list[int],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/attach-sender-emails"
        return self.request_json(
            "POST",
            path,
            json_body={"sender_email_ids": [str(x) for x in sender_email_ids]},
        )

    def remove_sender_emails(
        self,
        campaign_id: int,
        *,
        sender_email_ids: list[int],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/remove-sender-emails"
        return self.request_json(
            "DELETE",
            path,
            json_body={"sender_email_ids": [str(x) for x in sender_email_ids]},
        )

    def campaign_stats(
        self,
        campaign_id: int,
        *,
        start_date: str,
        end_date: str,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/stats"
        return self.request_json(
            "POST",
            path,
            json_body={"start_date": start_date, "end_date": end_date},
        )

    def campaign_replies(
        self,
        campaign_id: int,
        *,
        search: str | None = None,
        status: str | None = None,
        folder: str | None = None,
        read: bool | None = None,
        sender_email_id: int | None = None,
        lead_id: int | None = None,
        tag_ids: list[int] | None = None,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/replies"
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if status:
            params["status"] = status
        if folder:
            params["folder"] = folder
        if read is not None:
            params["read"] = read
        if sender_email_id is not None:
            params["sender_email_id"] = sender_email_id
        if lead_id is not None:
            params["lead_id"] = lead_id
        if tag_ids:
            params["tag_ids"] = tag_ids

        return self.request_json("GET", path, params=params or None)

    def stop_future_emails_for_leads(
        self,
        campaign_id: int,
        *,
        lead_ids: list[int],
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/leads/stop-future-emails"
        return self.request_json(
            "POST",
            path,
            json_body={"lead_ids": lead_ids},
        )

    def list_sender_emails(
        self,
        *,
        search: str | None = None,
        tag_ids: list[int] | None = None,
        excluded_tag_ids: list[int] | None = None,
        without_tags: bool | None = None,
    ) -> tuple[dict[str, Any], DebugInfo]:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if tag_ids:
            params["tag_ids"] = tag_ids
        if excluded_tag_ids:
            params["excluded_tag_ids"] = excluded_tag_ids
        if without_tags is not None:
            params["without_tags"] = without_tags

        return self.request_json(
            "GET",
            self.settings.sender_emails_path,
            params=params or None,
        )

    def campaign_details(
        self,
        campaign_id: int,
    ) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}"
        return self.request_json("GET", path)

    def pause_campaign(self, campaign_id: int) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/pause"
        return self.request_json("PATCH", path)

    def resume_campaign(self, campaign_id: int) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/resume"
        return self.request_json("PATCH", path)

    def archive_campaign(self, campaign_id: int) -> tuple[dict[str, Any], DebugInfo]:
        path = f"{self.settings.campaigns_path}/{campaign_id}/archive"
        return self.request_json("PATCH", path)

    def upload_leads_csv(
        self,
        *,
        name: str,
        csv_path: Path,
        columns_to_map: dict[str, str],
    ) -> tuple[dict[str, Any], DebugInfo]:
        url = f"{self.settings.base_url}/api/leads/bulk/csv"
        resp: httpx.Response | None = None

        headers = {
            "Authorization": f"Bearer {self.settings.api_token}",
            "Accept": "application/json",
        }
        form_data: dict[str, str] = {"name": name}
        for field_name, column_name in columns_to_map.items():
            form_data[f"columnsToMap[0][{field_name}]"] = column_name

        try:
            with csv_path.open("rb") as fh:
                files = {"csv": (csv_path.name, fh, "text/csv")}
                resp = self._client.request(
                    "POST",
                    "/api/leads/bulk/csv",
                    headers=headers,
                    data=form_data,
                    files=files,
                )
        except FileNotFoundError as e:
            raise NetworkError(f"CSV file not found: {csv_path}") from e
        except httpx.TimeoutException as e:
            raise NetworkError("Network timeout calling EmailBison") from e
        except httpx.HTTPError as e:
            raise NetworkError("Network error calling EmailBison") from e

        dbg = self._debug_summary(resp, method="POST", url=url)
        self._raise_for_status(resp)
        return _safe_json(resp), dbg

    def get_lead_list(
        self,
        lead_list_id: int,
    ) -> tuple[dict[str, Any], DebugInfo]:
        candidate_paths = [
            f"/api/leads/lists/{lead_list_id}",
            f"/api/lead-lists/{lead_list_id}",
        ]
        last_error: ApiError | None = None

        for path in candidate_paths:
            try:
                return self.request_json("GET", path)
            except ApiError as e:
                last_error = e
                if e.status_code == 404:
                    continue
                raise

        raise ApiError(
            f"Unable to fetch lead list {lead_list_id}; no supported endpoint found.",
            status_code=last_error.status_code if last_error else None,
            details=last_error.details if last_error else None,
        )


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"data": data}
    except Exception:
        return {"text": resp.text}
