"""Read-Only Dhan Connectivity & Endpoint Safety Smoke Test."""

from src.eye.option_capture.endpoint_guard import validate_request_url, redact_headers


def run_connectivity_smoke():
    print("=== PHASE E4A-E: CONNECTIVITY & ENDPOINT SAFETY SMOKE ===")
    urls = [
        "https://api.dhan.co/v2/optionchain",
        "https://api.dhan.co/v2/optionchain/expirylist",
        "https://api.dhan.co/v2/marketfeed/quote",
        "wss://api-feed.dhan.co",
    ]
    for url in urls:
        validate_request_url(url, method="POST")
        print(f"Validated read-only endpoint: {url}")

    sample_headers = {"access-token": "secret_token_123", "client-id": "11002233"}
    redacted = redact_headers(sample_headers)
    assert redacted["access-token"] == "[REDACTED_SECRET]"
    print("Header secret redaction verified successfully.")
    return "PASS"


if __name__ == "__main__":
    run_connectivity_smoke()
