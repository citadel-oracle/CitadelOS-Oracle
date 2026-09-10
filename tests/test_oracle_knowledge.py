import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.oracle.knowledge import KnowledgeVault, KnowledgeVaultError


pytestmark = [pytest.mark.unit, pytest.mark.safety]
VAULT_ROOT = Path(__file__).parents[1] / "oracle_knowledge"


def copy_vault(tmp_path):
    target = tmp_path / "oracle_knowledge"
    shutil.copytree(VAULT_ROOT, target)
    return target


def registry(root):
    return json.loads((root / "evidence_registry.json").read_text())


def write_registry(root, value):
    (root / "evidence_registry.json").write_text(
        json.dumps(value, indent=2) + "\n",
        encoding="utf-8",
    )


def vault_file_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_vault_hash_and_loading_are_deterministic():
    first = KnowledgeVault(VAULT_ROOT)
    second = KnowledgeVault(VAULT_ROOT)

    assert first.vault_version == "1.0.0"
    assert first.vault_hash == second.vault_hash
    assert len(first.vault_hash) == 64
    assert [item.item_id for item in first.items] == sorted(
        item.item_id for item in first.items
    )


def test_registry_entry_order_does_not_change_vault_hash(tmp_path):
    baseline = KnowledgeVault(VAULT_ROOT)
    root = copy_vault(tmp_path)
    document = registry(root)
    document["entries"].reverse()
    write_registry(root, document)

    reordered = KnowledgeVault(root)

    assert reordered.vault_hash == baseline.vault_hash
    assert reordered.items == baseline.items


def test_duplicate_ids_fail_closed(tmp_path):
    root = copy_vault(tmp_path)
    document = registry(root)
    document["entries"].append(dict(document["entries"][0]))
    write_registry(root, document)

    with pytest.raises(KnowledgeVaultError, match="Duplicate knowledge ID"):
        KnowledgeVault(root)


@pytest.mark.parametrize("defect", ["source", "reference"])
def test_invalid_source_and_content_references_fail_closed(tmp_path, defect):
    root = copy_vault(tmp_path)
    document = registry(root)
    if defect == "source":
        document["entries"][0]["source_tag"] = "UNREGISTERED_SOURCE"
        match = "Unknown source tag"
    else:
        document["entries"][0]["content_path"] = "../outside.md"
        match = "escapes vault"
    write_registry(root, document)

    with pytest.raises(KnowledgeVaultError, match=match):
        KnowledgeVault(root)


def test_malformed_registry_fails_closed(tmp_path):
    root = copy_vault(tmp_path)
    (root / "evidence_registry.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(KnowledgeVaultError, match="unreadable"):
        KnowledgeVault(root)


def test_orphan_contradiction_link_fails_closed(tmp_path):
    root = copy_vault(tmp_path)
    document = registry(root)
    document["entries"][0]["contradictions"] = ["kv.missing.reference"]
    write_registry(root, document)

    with pytest.raises(KnowledgeVaultError, match="Invalid contradiction link"):
        KnowledgeVault(root)


def test_search_by_id_topic_and_tag_is_exact():
    vault = KnowledgeVault(VAULT_ROOT)
    item = vault.get("KV.VOB.INTERPRETATION")

    assert item is not None
    assert item.item_id == "kv.vob.interpretation"
    assert vault.search(item_id="kv.vob.interpretation") == (item,)
    assert vault.search(topic="vob") == (item,)
    assert item in vault.search(tag="completed-candles")
    assert vault.search(tag="not-a-real-tag") == ()


def test_explicitly_empty_search_values_return_no_results():
    vault = KnowledgeVault(VAULT_ROOT)

    assert vault.search() == vault.items
    assert vault.search(item_id="") == ()
    assert vault.search(topic="   ") == ()
    assert vault.search(tag="") == ()


def test_vault_is_read_only_and_search_does_not_touch_files():
    before = vault_file_hashes(VAULT_ROOT)
    vault = KnowledgeVault(VAULT_ROOT)
    item = vault.items[0]

    with pytest.raises(FrozenInstanceError):
        item.status = "VALIDATED"
    vault.search(topic=item.topic)

    assert vault_file_hashes(VAULT_ROOT) == before


def test_seeded_items_are_truthful_hypotheses_with_required_contract():
    vault = KnowledgeVault(VAULT_ROOT)

    assert len(vault.items) == 12
    assert {item.status for item in vault.items} == {"HYPOTHESIS"}
    for item in vault.items:
        assert item.definition
        assert item.rule
        assert item.valid_conditions
        assert item.invalidation
        assert item.when_not_to_use
        assert item.testable_hypothesis
