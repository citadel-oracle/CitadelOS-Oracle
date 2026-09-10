"""Fail closed before publishing role output. Never silently discard bad citations."""
from src.oracle_sol.reasoning_protocol import validate_structured_model_output


def cognitive_output_error(raw, schema, packet):
    if validate_structured_model_output(raw, schema):
        return "SCHEMA_INVALID"
    cited = []

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if "evidence_id" in key:
                    cited.extend(child if isinstance(child, list) else [child])
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(raw)
    for reference in cited:
        if (not isinstance(reference, str) or
                reference.startswith(("peer:", "model:", "qwen:", "gemini:")) or
                reference not in packet.valid_evidence_ids or packet.resolve_evidence(reference) is None):
            return "MODEL_CLAIM_UNSUPPORTED"
    return None
