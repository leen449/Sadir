"""Firebase persistence for GraphShield reports.

Responsibilities:
- Initialize Firebase Admin from Base64-encoded service-account JSON.
- Upload report PDFs to Firebase Storage.
- Store report metadata in Firestore.
- List report history for the shared internal workspace.
- Download a stored PDF by its Storage path.

No public URLs are created. PDFs remain private and are read through the
trusted backend using Firebase Admin credentials.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import auth as firebase_auth, credentials, firestore, storage


load_dotenv()

_REPORTS_COLLECTION = "reports"
_REPORTS_PREFIX = "reports"


def initialize_firebase():
    """Initialize Firebase Admin once and return the default app."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    encoded_credentials = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "").strip()
    if not encoded_credentials:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_B64 is missing from environment variables."
        )

    try:
        decoded_bytes = base64.b64decode(encoded_credentials, validate=True)
        service_account_info = json.loads(decoded_bytes.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Failed to decode FIREBASE_SERVICE_ACCOUNT_B64. "
            "Make sure it contains the Base64 value of the complete service-account JSON."
        ) from exc

    storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if not storage_bucket:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET is missing from environment variables.")

    # Admin SDK expects the bucket name, not a gs:// URL.
    storage_bucket = storage_bucket.removeprefix("gs://").rstrip("/")

    cred = credentials.Certificate(service_account_info)
    return firebase_admin.initialize_app(
        cred,
        {"storageBucket": storage_bucket},
    )


def _db():
    initialize_firebase()
    return firestore.client()


def _bucket():
    initialize_firebase()
    return storage.bucket()


# =====================================================================
# CORRECTED AUTHENTICATION FLOW
#
# Do NOT create a "phone_otps" collection in Firestore.
# Manage your test numbers and static OTP codes inside the Firebase Auth Console.
# Your frontend/client will log the user in using that test number and OTP,
# which generates an 'id_token'. Your API passes that token here.
# =====================================================================

def verify_user_token(id_token: str) -> dict[str, Any]:
    """Verify the Firebase ID token sent from the client/frontend.

    This works for both real phone logins and Firebase Auth test phone numbers.
    Returns a dictionary of decoded user claims on success.
    Raises ValueError if the token is invalid, expired, or missing.
    """
    id_token = str(id_token or "").strip()
    if not id_token:
        raise ValueError("Authentication token is required.")

    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        return {
            "uid": decoded_token.get("uid"),
            "phone_number": decoded_token.get("phone_number"),
            "auth_time": decoded_token.get("auth_time"),
        }
    except firebase_auth.ExpiredIdTokenError:
        raise ValueError("The authentication session has expired. Please log in again.")
    except firebase_auth.InvalidIdTokenError:
        raise ValueError("Invalid authentication token.")
    except Exception as exc:
        raise ValueError(f"Authentication failed: {exc}")

def _safe_filename(filename: str) -> str:
    """Keep a readable filename while removing unsafe path characters."""
    base = os.path.basename(str(filename)).strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned


def _report_id_from_filename(filename: str) -> str:
    """Extract GS-YYYY-NNNNN from the current report filename when available."""
    match = re.match(r"^(GS-\d{4}-\d+)_", os.path.basename(filename))
    if match:
        return match.group(1)
    return os.path.splitext(os.path.basename(filename))[0]



def save_report(
    *,
    pdf_bytes: bytes,
    filename: str,
    transaction_id: str,
    status: str = "Under Investigation",
) -> dict[str, Any]:
    """Upload one PDF and persist its metadata.

    The Firestore document uses an auto-generated ID so reports created by
    different teammates cannot overwrite each other. The Storage object path
    also contains a UUID for the same reason.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes:
        raise ValueError("pdf_bytes must contain a non-empty PDF file.")

    transaction_id = str(transaction_id)
    safe_filename = _safe_filename(filename)
    report_id = _report_id_from_filename(safe_filename)
    now = datetime.now(timezone.utc)

    unique_suffix = uuid.uuid4().hex
    storage_path = (
        f"{_REPORTS_PREFIX}/{now.year}/"
        f"{report_id}_{transaction_id}_{unique_suffix}.pdf"
    )

    bucket = _bucket()
    blob = bucket.blob(storage_path)

    print(
        f"[FIREBASE][REPORT] upload starting | report_id={report_id} "
        f"| txid={transaction_id} | path={storage_path} | bytes={len(pdf_bytes)}"
    )

    blob.upload_from_string(bytes(pdf_bytes), content_type="application/pdf")

    metadata = {
        "report_id": report_id,
        "transaction_id": transaction_id,
        "generated_at": firestore.SERVER_TIMESTAMP,
        "status": str(status),
        "filename": safe_filename,
        "storage_path": storage_path,
        "content_type": "application/pdf",
        "size_bytes": len(pdf_bytes),
    }

    try:
        doc_ref = _db().collection(_REPORTS_COLLECTION).document()
        doc_ref.set(metadata)
    except Exception:
        # Avoid orphaning a PDF if its metadata write fails.
        try:
            blob.delete()
        except Exception as rollback_exc:
            print(
                f"[FIREBASE][REPORT] rollback failed | path={storage_path} "
                f"| {type(rollback_exc).__name__}: {rollback_exc}"
            )
        raise

    print(
        f"[FIREBASE][REPORT] save success | doc_id={doc_ref.id} "
        f"| report_id={report_id} | txid={transaction_id}"
    )

    return {
        "document_id": doc_ref.id,
        **metadata,
        # Local timestamp for immediate caller use; Firestore still stores a
        # server timestamp as the source of truth.
        "generated_at": now,
    }


def get_reports(
    *,
    limit: int = 100,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return shared report history, newest first.

    With no login system, this intentionally returns the shared internal report
    history. Date filters are applied on Firestore's generated_at timestamp.
    """
    if limit <= 0:
        return []

    query = _db().collection(_REPORTS_COLLECTION)

    if start_date is not None:
        start_dt = datetime.combine(start_date, dt_time.min, tzinfo=timezone.utc)
        query = query.where("generated_at", ">=", start_dt)

    if end_date is not None:
        # Exclusive upper bound at the next midnight is simpler and avoids
        # losing reports with sub-second timestamps late in the day.
        end_dt = datetime.combine(end_date, dt_time.max, tzinfo=timezone.utc)
        query = query.where("generated_at", "<=", end_dt)

    query = query.order_by("generated_at", direction=firestore.Query.DESCENDING).limit(limit)

    reports: list[dict[str, Any]] = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        data["document_id"] = snapshot.id
        reports.append(data)

    print(f"[FIREBASE][REPORT] history loaded | count={len(reports)}")
    return reports


def download_report(storage_path: str) -> bytes:
    """Download a private report PDF from Firebase Storage."""
    storage_path = str(storage_path or "").strip()
    if not storage_path or not storage_path.startswith(f"{_REPORTS_PREFIX}/"):
        raise ValueError("Invalid report storage path.")

    print(f"[FIREBASE][REPORT] download starting | path={storage_path}")
    pdf_bytes = _bucket().blob(storage_path).download_as_bytes()
    print(
        f"[FIREBASE][REPORT] download success | path={storage_path} "
        f"| bytes={len(pdf_bytes)}"
    )
    return pdf_bytes


def get_report_download_url(
    storage_path: str,
    *,
    filename: str | None = None,
    expires_minutes: int = 15,
) -> str:
    """Create a short-lived signed download URL for a private PDF."""
    storage_path = str(storage_path or "").strip()
    if not storage_path or not storage_path.startswith(f"{_REPORTS_PREFIX}/"):
        raise ValueError("Invalid report storage path.")

    safe_name = _safe_filename(filename or os.path.basename(storage_path))
    blob = _bucket().blob(storage_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=max(1, int(expires_minutes))),
        method="GET",
        response_disposition=f'attachment; filename="{safe_name}"',
    )
