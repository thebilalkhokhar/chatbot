from __future__ import annotations

from pathlib import Path

import pytest

from chatbot.bot.capability import (
    PRIMER_NAME,
    PRIMER_TOKEN_BUDGET,
    Candidate,
    CapabilityError,
    Registry,
    estimate_tokens,
    fold,
    parse_tables,
    value_forms,
)
from chatbot.bot.state import FAMILIES

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "kb"
CORPUS_DIR = ROOT / "kb_v2"


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load(KB_DIR)


def write_registry(capabilities: Path, body: str) -> Path:
    """A capabilities dir holding one registry plus the minimal allow-list the loader requires."""
    capabilities.mkdir(parents=True, exist_ok=True)
    (capabilities / "compliance-allowlist.md").write_text(
        "# Allow-list\n\n```capability\n# table: allowed\n# topic|family|say|source|never_say\n"
        "bars|boxes|Food-grade, SBA-certified|kb_v2/site/site-about-us.md|never say ISO 9001\n"
        "```\n\n```capability\n# table: never\n# claim|family|why\nFSC certified|boxes|no registration number on record\n```\n",
        encoding="utf-8",
    )
    path = capabilities / "capability-registry.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_registry_loads_the_expected_row_counts(registry):
    # these are what the kb_v2 extraction produces; `chatbot capability` reports the same numbers
    assert len(registry.offerings) == 147
    assert len(registry.exclusions) == 26
    assert len(registry.sizes) == 6
    assert len(registry.gauges) == 29
    assert len(registry.production_questions) == 8
    assert len(registry.not_attested) == 56
    assert len(registry.unmapped) == 5
    assert len(registry.claims) == 24
    assert len(registry.bans) == 22
    assert registry.aliases, "the fold table is what makes site spelling queryable"


def test_validate_is_clean(registry):
    errors, warnings = registry.validate(CORPUS_DIR)
    assert errors == []
    assert warnings == []


def test_every_citation_points_at_a_real_corpus_file(registry):
    cited = [row.source for row in registry.offerings]
    cited += [row.source for row in registry.exclusions]
    cited += [row.source for row in registry.gauges if row.gauge]
    cited += [row.source for row in registry.production_questions]
    assert len(cited) == len(registry.offerings) + len(registry.exclusions) + 28 + 8
    for source in cited:
        assert "kb_v2/" in source, source


def test_the_draft_registry_has_no_signed_rows(registry):
    # D-2/D-10 sign-off is still pending, so nothing may be asserted as a capability yet
    assert not any(row.signed for row in registry.offerings)
    assert all(row.approved.strip().lower() == "pending" for row in registry.offerings)
    assert all(row.approved.strip().lower() == "pending" for row in registry.exclusions)


def test_rows_load_as_typed_data(registry):
    for row in registry.offerings:
        assert row.family in FAMILIES, row
        assert row.scope == "page", f"every kb_v2 row is one product page: {row}"
        assert row.approved == "pending"
    for row in registry.exclusions:
        assert row.reason and row.source, row
    for row in registry.gauges:
        assert row.family in FAMILIES and row.material, row
    for row in registry.claims:
        assert row.say and row.source, row
    for row in registry.bans:
        assert row.claim and row.why, row


def test_kb_v2_states_no_mechanical_pair_exclusion_yet(registry):
    # every kb_v2 refusal is a use-case rule; a pair row would refuse builds the site actually sells,
    # so the tuple matcher stays unused until Sales attests a real pair
    assert all(row.kind == "rule" for row in registry.exclusions)
    assert not any(row.mechanical for row in registry.exclusions)


def test_classify_states(registry):
    attested_shape = Candidate.of(
        "bags",
        style="stand up pouch",
        material=("PE", "foil"),
        finish="soft touch",
        extras="easy-open zipper",
    )
    match = registry.classify(attested_shape)
    assert match.state == "unknown_capability"
    assert len(match.offerings) == 1
    assert "unsigned" in match.reason
    assert match.may_assert is False

    invented = registry.classify(Candidate.of("boxes", style="pillow box"))
    assert invented.state == "unknown_capability"
    assert not invented.offerings
    assert registry.is_not_attested("pillow box") is not None


def test_a_pair_exclusion_is_the_only_kind_of_mechanical_refusal(tmp_path):
    body = "\n".join(
        [
            "# Registry",
            "",
            "```capability",
            "# table: vocabulary",
            "# family|slot|values",
            "boxes|style|Mailer Boxes",
            "boxes|material|kraft; rigid cardboard",
            "boxes|finish|matte lamination",
            "```",
            "",
            "```capability",
            "# table: supported",
            "# family|style|material|insert|finish|extras|gauge|scope|source|approved|note",
            "boxes|Mailer Boxes|kraft|-|matte lamination|-|-|page|"
            "kb_v2/catalog/catalog-mailer-boxes.md|pending|one page",
            "```",
            "",
            "```capability",
            "# table: excluded",
            "# family|kind|style|material|insert|finish|extras|reason|source|approved",
            "boxes|pair|mailer box|kraft|-|-|-|kraft mailers are refused with a window "
            "on this page|kb_v2/catalog/catalog-mailer-boxes.md|pending",
            "```",
            "",
        ]
    )
    write_registry(tmp_path / "capabilities", body)
    local = Registry.load(tmp_path)

    refused = local.classify(Candidate.of("boxes", style="mailer box", material="kraft"))
    assert refused.state == "excluded"
    assert refused.exclusion is not None
    assert "window" in refused.reason

    # the same style on a stock the pair does not name stays discussable
    other = local.classify(Candidate.of("boxes", style="mailer box", material="rigid cardboard"))
    assert other.state == "unknown_capability"
    assert other.offerings == ()


def test_the_normaliser_folds_site_spelling_before_a_tuple_is_built(registry):
    assert registry.normalise("boxes", "finish", "Softtouch Lamination").value == "soft touch lamination"
    assert registry.normalise("boxes", "material", "GreyBoard").value == "grayboard"
    assert registry.normalise("banners", "material", "Corflute").value == "corrugated plastic"
    assert registry.normalise("boxes", "material", "Rigid stocks").value == "rigid board"
    # a spelling with no alias row of its own still reaches the same row, because covering folds too
    assert fold(registry.normalise("boxes", "finish", "Soft-Touch Lamination").value) == "soft touch lamination"
    assert registry.classify(
        Candidate.of("boxes", style="perfume box", finish="Soft-Touch Lamination")
    ).offerings


def test_rigid_names_a_box_stock_and_stays_discussable(registry):
    # "rigid" is a box material on these pages, never a product name
    moved = registry.normalise("boxes", "style", "rigid")
    assert (moved.family, moved.slot, moved.value) == ("boxes", "material", "rigid cardboard")
    match = registry.classify(
        Candidate.of("boxes", style="perfume box", material=moved.value, finish="foil stamping")
    )
    assert match.state == "unknown_capability"
    assert match.offerings
    assert match.may_assert is False


def test_unknown_values_reports_invented_nouns(registry):
    unknown = registry.unknown_values(Candidate.of("bags", extras=("weatherproof", "easy-open zipper")))
    assert unknown == {"extras": ("weatherproof",)}
    assert registry.unknown_values(Candidate.of("bags", style="stand-up pouch")) == {}


def test_normaliser_rules(registry):
    decal = registry.normalise("boxes", "style", "decal")
    assert (decal.family, decal.slot, decal.value) == ("banners", "style", "decal")
    sticker = registry.normalise("banners", "style", "sticker")
    assert (sticker.family, sticker.slot, sticker.value) == ("labels", "style", "sticker")

    matte = registry.normalise("bags", "material", "matte")
    assert (matte.slot, matte.value) == ("finish", "matte")

    zipper = registry.normalise("bags", "finish", "resealable zipper")
    assert (zipper.slot, zipper.value) == ("extras", "resealable zipper")

    pack = registry.normalise("bags", "size", "100 pack")
    assert pack.answers_nothing is True and pack.value == ""

    unitless = registry.normalise("bags", "size", "10x12")
    assert unitless.answers_nothing is True and unitless.value == ""

    passthrough = registry.normalise("bags", "style", "stand-up pouch")
    assert (passthrough.slot, passthrough.answers_nothing) == ("style", False)
    assert fold(passthrough.value) in value_forms("Stand Up Pouches")


def test_value_forms_bridge_page_titles_and_customer_wording():
    assert value_forms("Mailer Boxes") & value_forms("mailer box")
    assert value_forms("Pull up Banners") & value_forms("pull-up banner")
    assert not value_forms("Coffee Bags") & value_forms("Mylar Bags")


def test_gauge_figures_carry_their_material_and_basis(registry):
    card = registry.gauge_for("13 pt")
    assert (card.family, card.basis) == ("business_cards", "page")
    assert card.material == "cardstock"

    pouch = registry.gauge_for("80 to 150 micron")
    assert (pouch.family, pouch.basis) == ("bags", "faq")

    coroplast = registry.gauge_for("4 mm")
    assert (coroplast.family, coroplast.basis) == ("banners", "knowledge")

    assert registry.gauge_for("99pt") is None
    labels = next(row for row in registry.gauges if row.family == "labels")
    assert not labels.gauge, "no label page in kb_v2 states a face-stock gauge"
    assert "no label" in labels.note


def test_only_two_families_publish_a_size_grid(registry):
    boxes = next(row for row in registry.sizes if row.family == "boxes")
    assert not boxes.values
    assert "visitor" in boxes.note
    assert boxes.source

    published = sorted(row.family for row in registry.sizes if row.values)
    assert published == ["banners", "print"]
    pull_up = next(row for row in registry.sizes if row.family == "banners")
    assert '23" x 66"' in pull_up.values


def test_families_match_state_and_registry(registry):
    assert registry.families == tuple(name for name in FAMILIES if name != "unknown")
    assert set(registry.vocabulary) == set(registry.families)


def test_primer_renders_every_family_and_stays_in_budget(registry):
    primer = registry.render_primer()
    assert estimate_tokens(primer) <= PRIMER_TOKEN_BUDGET
    for family in registry.families:
        assert family.upper().replace("_", " ") in primer
    assert "DO NOT OFFER" in primer
    assert "pillow box" in primer
    assert "Stand Up Pouches" in primer
    assert "GAUGES NOT FOR THE REPLY" in primer
    assert "COLOUR is not a capability" in primer
    assert "form_selectable" not in primer
    # a v1 phrase kb_v2 never uses must not be resurrected by the primer
    assert "high-barrier metalized foil" not in primer
    assert registry.render_primer() == primer


def test_primer_file_round_trips_and_drift_is_visible(registry, tmp_path):
    path = registry.write_primer(tmp_path)
    assert path.read_text(encoding="utf-8") == registry.render_primer()
    path.write_text(path.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    assert path.read_text(encoding="utf-8") != registry.render_primer()


def test_cli_capability_is_green_and_detects_primer_drift(config, capsys):
    from chatbot.bot.cli import cmd_capability

    assert cmd_capability(config, None) == 0
    out = capsys.readouterr().out
    assert '"errors": []' in out
    assert '"warnings": []' in out
    assert '"offerings": 147' in out

    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / PRIMER_NAME).write_text("hand edited\n", encoding="utf-8")
    assert cmd_capability(config, None) == 1
    assert "does not match the registry" in capsys.readouterr().out


def test_cli_ingest_writes_the_primer(config):
    from chatbot.bot.cli import cmd_ingest

    assert cmd_ingest(config, None) == 0
    written = (config.data_dir / PRIMER_NAME).read_text(encoding="utf-8")
    assert written == Registry.load(KB_DIR).render_primer()


def test_load_rejects_a_vocabulary_slot_the_loader_does_not_read(tmp_path):
    body = "\n".join(
        [
            "# Registry",
            "",
            "```capability",
            "# table: vocabulary",
            "# family|slot|values",
            "boxes|style|Mailer Boxes",
            "boxes|free_params|window",
            "```",
            "",
        ]
    )
    write_registry(tmp_path / "capabilities", body)
    with pytest.raises(CapabilityError, match="silently disappears"):
        Registry.load(tmp_path)


def test_parse_tables_rejects_a_malformed_row():
    good = "```capability\n# table: demo\n# a|b\n1|2\n```\n"
    assert parse_tables(good, Path("demo.md"))["demo"] == [{"a": "1", "b": "2"}]

    with pytest.raises(CapabilityError):
        parse_tables("```capability\n# table: demo\n# a|b\n1|2|3\n```\n", Path("demo.md"))
    with pytest.raises(CapabilityError):
        parse_tables("```capability\n# table: demo\n# a|b\n1|2\n", Path("demo.md"))
    with pytest.raises(CapabilityError):
        parse_tables("```capability\n1|2\n```\n", Path("demo.md"))
