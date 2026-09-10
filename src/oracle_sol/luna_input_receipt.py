"""Content-addressed request records beside the existing Sol durable ledgers."""
import hashlib
import json
import os
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def persist_receipt(directory, request_bytes, packet):
    body = request_bytes.decode("utf-8")
    request = json.loads(body)
    payload = json.loads(request["messages"][-1]["content"])
    receipt = {
        "schema_version": "luna-input-v1",
        "receipt_id": hashlib.sha256(request_bytes).hexdigest(),
        "request_body": body,
        "model": request["model"],
        "session_id": packet.session_id,
        "revision": packet.revision,
        "frontier": list(packet.unseen_event_ids),
        "cutoff": payload["decision_cutoff_ist"],
        "observed_at": payload["frozen_at_utc"],
        "payload": payload,
        "packet_hash": digest(payload),
        "parent_receipt_id": hashlib.sha256(digest(payload).encode()).hexdigest(),
    }
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (receipt["receipt_id"] + ".json")
    encoded = json.dumps(receipt, sort_keys=True, allow_nan=False)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("INPUT_RECEIPT_COLLISION_OR_CORRUPTION")
    # Ensure the newly created directory entry is durable before network dispatch.
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return receipt


def valid_binding(receipt, response, session, revision, model):
    try:
        request = json.loads(receipt["request_body"])
        return (
            hashlib.sha256(receipt["request_body"].encode()).hexdigest() == receipt["receipt_id"]
            and json.loads(request["messages"][-1]["content"]) == receipt["payload"]
            and request["model"] == receipt["model"] == model
            and receipt["session_id"] == receipt["payload"]["session_date"] == session
            and receipt["revision"] == receipt["payload"]["revision"] == revision
            and receipt["frontier"] == receipt["payload"]["evidence_frontier"]
            and receipt["cutoff"] == receipt["payload"]["decision_cutoff_ist"]
            and receipt["observed_at"] == receipt["payload"]["frozen_at_utc"]
            and receipt.get("packet_hash", digest(receipt["payload"])) == digest(receipt["payload"])
            and receipt.get("parent_receipt_id", hashlib.sha256(digest(receipt["payload"]).encode()).hexdigest()) == hashlib.sha256(digest(receipt["payload"]).encode()).hexdigest()
            and receipt["output_hash"] == digest(response)
        )
    except (KeyError, TypeError, ValueError):
        return False
