"""Upload one verified video file to a Google Shared Drive folder, and
(Bước 6 of the 14/09 fix chain) create the one-folder-per-job that files
land inside.

Phase 03's replacement for the "download from a public folder" pipeline in
`gdrive.py` (that module is `gdown`-only, no OAuth, download-direction only
per its own docstring — intentionally left untouched; this file does not
import it and does not reuse any of its code).

This module never keeps state across calls beyond a lazily-built API
client: it answers exactly one question per call — "did this one file (or
folder) land in the Shared Drive, and if not, why?" Retry counting /
backpressure / the per-job folder-id CACHE across many uploads lives in
`web/lifecycle.py`, not here.

Three-state result, never collapsed to a bool (phase-03 constraint 2):
  - SUCCESS        -> uploaded, `drive_id` is a real Shared Drive id
  - NOT_CONFIGURED -> no credential/folder configured; nothing was attempted
  - FAILED         -> credential + folder WERE configured, the call itself
                      failed (network, quota, permission, bad response, ...)

Collapsing NOT_CONFIGURED and FAILED into one value is exactly the mistake
`~/.claude/rules/guard-marker-and-claim-write-ordering.md` warns about:
"not yet configured" and "configured but broken" need different operator
responses, and gluing them together turns a real outage into silence.
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("ttmd.gdrive_upload")

# No hardcoded default path: an unset env var IS the "chưa cấu hình" state,
# not a fallback to guess at. Ops sets these on the target machine only.
ENV_SERVICE_ACCOUNT_FILE = "GDRIVE_SERVICE_ACCOUNT_FILE"
ENV_SHARED_DRIVE_FOLDER_ID = "GDRIVE_SHARED_DRIVE_FOLDER_ID"

_SCOPES = ["https://www.googleapis.com/auth/drive"]


class UploadOutcome(str, Enum):
    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


@dataclass(frozen=True)
class UploadResult:
    """Never carries credential contents or paths — safe to log, or to show
    on the UI/API response, without a second thought."""

    outcome: UploadOutcome
    file_id: str | None = None
    drive_id: str | None = None
    web_view_link: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is UploadOutcome.SUCCESS


def _tighten_credential_permissions(path: Path) -> None:
    """Best-effort: a service-account key is a bearer secret. Restrict to
    owner-only READ+WRITE (0600) if it is any wider than that — this is a
    FILE, not a directory, so the execute bit is dead weight, not a
    tightened permission. Never widen permissions; never raise — a
    filesystem that rejects chmod (some CI sandboxes, some network mounts)
    must not block the upload. It only means this defense-in-depth layer
    did not apply on this run."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            path.chmod(0o600)
    except OSError:
        log.warning("không siết được quyền file credential Drive — bỏ qua bước này")


class DriveUploader:
    """One Shared Drive folder, reachable through one service account.

    Real `googleapiclient` / `google.oauth2` calls are isolated to
    `_build_service` and `_create_drive_object` (the shared path both
    `upload_file` and `create_job_folder` call into), and the google client
    libraries are imported lazily inside those methods — so tests
    exercising the "not configured" path, or injecting a fake service via
    `_build_service`, never need the libraries installed or any real
    credential. See `web/lifecycle.py`'s tests for the injection pattern.
    """

    def __init__(self, service_account_file: str | None = None,
                 folder_id: str | None = None):
        self._service_account_file = service_account_file or os.environ.get(
            ENV_SERVICE_ACCOUNT_FILE)
        self._folder_id = folder_id or os.environ.get(ENV_SHARED_DRIVE_FOLDER_ID)
        # Only the CREDENTIALS are cached — never the service/transport. See
        # `_build_service`'s docstring for why (Broken pipe lesson from
        # ~/meta-ads-automation's creative_drive_client.py).
        self._credentials: Any = None

    def is_configured(self) -> bool:
        return bool(
            self._service_account_file
            and self._folder_id
            and Path(self._service_account_file).is_file()
        )

    def _build_service(self) -> Any:
        """Build a FRESH Drive v3 service — a new httplib2 transport, a new
        socket — on EVERY call. Never cache the service object itself.

        httplib2's default transport is not safe to reuse across calls with
        long idle gaps in between: the underlying socket goes stale and the
        next call fails with a Broken pipe. A job here can run for hours
        with only a handful of uploads in it — exactly the idle-gap shape
        that trips this. Same failure mode, same fix, already paid for once
        in `~/meta-ads-automation/backend/app/services/creative_drive_client.py`
        ("FIX (broken-pipe on 2nd+ call)"): cache only the credentials
        (cheap, stateless), rebuild the service every time.
        """
        from googleapiclient.discovery import build

        return build("drive", "v3", credentials=self._get_credentials(), cache_discovery=False)

    def _get_credentials(self) -> Any:
        if self._credentials is not None:
            return self._credentials
        from google.oauth2 import service_account

        assert self._service_account_file is not None  # is_configured() already checked
        cred_path = Path(self._service_account_file)
        _tighten_credential_permissions(cred_path)
        self._credentials = service_account.Credentials.from_service_account_file(
            str(cred_path), scopes=_SCOPES,
        )
        return self._credentials

    def upload_file(self, path: Path, parent_folder_id: str | None = None) -> UploadResult:
        """Upload one file. `parent_folder_id` overrides the top-level
        configured folder — Bước 6 passes the job's own per-job folder
        (from `create_job_folder`) here so every video lands inside it
        instead of directly in the Shared Drive root."""
        if not self.is_configured():
            return UploadResult(
                outcome=UploadOutcome.NOT_CONFIGURED,
                reason=(
                    "Google Drive chưa được cấu hình "
                    f"({ENV_SERVICE_ACCOUNT_FILE}/{ENV_SHARED_DRIVE_FOLDER_ID} "
                    "thiếu hoặc file credential không tồn tại)"
                ),
            )
        metadata = {"name": path.name, "parents": [parent_folder_id or self._folder_id]}
        return self._create_drive_object(metadata, media_path=path, label=path.name)

    def create_job_folder(self, job_id: int) -> UploadResult:
        """Create one Drive folder for this job, inside the configured
        Shared Drive folder. Reuses `UploadResult`'s 3-state shape: on
        SUCCESS, `file_id` is the FOLDER's id — pass it straight into
        `upload_file(path, parent_folder_id=result.file_id)` — and
        `web_view_link` is the folder's browser link to persist via
        `web/models.py::set_job_drive_folder_link`."""
        if not self.is_configured():
            return UploadResult(
                outcome=UploadOutcome.NOT_CONFIGURED,
                reason=(
                    "Google Drive chưa được cấu hình "
                    f"({ENV_SERVICE_ACCOUNT_FILE}/{ENV_SHARED_DRIVE_FOLDER_ID} "
                    "thiếu hoặc file credential không tồn tại)"
                ),
            )
        metadata = {
            "name": f"job-{job_id}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [self._folder_id],
        }
        return self._create_drive_object(metadata, media_path=None, label=f"job-{job_id} folder")

    def _create_drive_object(self, metadata: dict[str, Any], *, media_path: Path | None,
                              label: str) -> UploadResult:
        """Shared `files().create(...)` + driveId-check path for both a
        video file (`media_path` set) and a job folder (`media_path` None,
        no `media_body`). Both must land inside the configured Shared
        Drive — a response without `driveId` means it did not, regardless
        of which kind of object was being created."""
        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload

            service = self._build_service()
            create_kwargs: dict[str, Any] = {
                "body": metadata,
                "fields": "id,driveId,webViewLink",
                # Constraint 1 (measured 14/09): missing this is a SILENT
                # failure — the object lands in the service account's own
                # 15GB "My Drive" instead of the Shared Drive, and stays
                # green until that private quota hits ~10k items and fails
                # hard.
                "supportsAllDrives": True,
            }
            if media_path is not None:
                create_kwargs["media_body"] = MediaFileUpload(str(media_path), resumable=False)
            response = service.files().create(**create_kwargs).execute()
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            log.error("Drive create trượt (HTTP %s) cho %s", status, label)
            return UploadResult(outcome=UploadOutcome.FAILED,
                                 reason=f"Drive API lỗi HTTP {status}")
        except Exception as exc:  # noqa: BLE001 — must never raise into the caller
            # type(exc).__name__ only — never str(exc): a Drive/network
            # exception message can echo back request internals, and this
            # reason string is safe-to-log / safe-to-show-on-UI by contract.
            log.error("Drive create trượt cho %s: %s", label, type(exc).__name__)
            return UploadResult(outcome=UploadOutcome.FAILED,
                                 reason=f"tạo trên Drive trượt: {type(exc).__name__}")

        drive_id = response.get("driveId")
        if not drive_id:
            # Landed somewhere that is not a Shared Drive despite the flag
            # above (e.g. folder_id itself is not inside one) -> the object
            # is NOT where ops assumes it is. FAILED, not SUCCESS, so the
            # local copy (for a file) is kept instead of silently
            # vanishing into the wrong quota.
            log.error("Drive create cho %s thiếu driveId — không nằm trong Shared Drive nào",
                       label)
            return UploadResult(
                outcome=UploadOutcome.FAILED,
                reason="tạo xong nhưng thiếu driveId (không thuộc Shared Drive nào)",
            )
        return UploadResult(
            outcome=UploadOutcome.SUCCESS,
            file_id=response.get("id"),
            drive_id=drive_id,
            web_view_link=response.get("webViewLink"),
        )
