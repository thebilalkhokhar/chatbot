from chatbot.bot.kb import Chunk, KBIndex, load_or_build


def _chunk(title: str, text: str) -> Chunk:
    return Chunk(
        id=f"{title}#1",
        doc_id=title.lower().replace(" ", "-"),
        title=title,
        category="products",
        source="test",
        status="verified",
        last_reviewed="2026-10-30",
        section="Materials",
        text=text,
        families=("labels",),
    )


def test_loader_uses_the_site_index_when_it_is_present(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "note.md").write_text(
        "---\nid: note\ntitle: Old notes\ncategory: facts\nstatus: verified\n---\n\nPP white vinyl only\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    KBIndex.build(kb).save(data / "kb_index.json")
    KBIndex(chunks=[_chunk("Bottle Labels", "PLA, ABS, and nylon")]).save(data / "kb_index_v2.json")

    loaded = load_or_build(kb, data)

    assert [chunk.title for chunk in loaded.chunks] == ["Bottle Labels"]


def test_loader_falls_back_to_the_notes_index(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "note.md").write_text(
        "---\nid: note\ntitle: Old notes\ncategory: facts\nstatus: verified\n---\n\nPP white vinyl only\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    KBIndex.build(kb).save(data / "kb_index.json")

    loaded = load_or_build(kb, data)

    assert any(chunk.title == "Old notes" for chunk in loaded.chunks)
