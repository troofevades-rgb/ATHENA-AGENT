"""T4-01.7 — Ollama image-block normalisation.

Pins the bridge from vision_analyze's content-list message shape
to Ollama's native ``content + images=`` shape so describe mode
actually works end-to-end on a local multimodal model.
"""

from __future__ import annotations

from athena.providers.ollama import _normalize_vision_messages


def test_text_only_message_passes_through_untouched():
    msgs = [{"role": "user", "content": "hello"}]
    out = _normalize_vision_messages(msgs)
    assert out == msgs
    assert out is not msgs  # fresh list


def test_text_only_list_content_collapses_to_string():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "first line"},
        {"type": "text", "text": "second line"},
    ]}]
    out = _normalize_vision_messages(msgs)
    assert out[0]["content"] == "first line\nsecond line"
    assert "images" not in out[0]


def test_single_image_block_moves_to_images_list():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "what's in this?"},
        {"type": "image", "media_type": "image/png", "data": "AAAA", "label": "image"},
    ]}]
    out = _normalize_vision_messages(msgs)
    m = out[0]
    assert m["role"] == "user"
    # The image label is inlined for the model to refer to.
    assert "what's in this?" in m["content"]
    assert "[image: image]" in m["content"]
    # And the bare base64 string lands in images=.
    assert m["images"] == ["AAAA"]


def test_multiple_tiles_carry_distinct_labels_inline():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "describe the whole scene"},
        {"type": "image", "data": "T1", "label": "tile_0_0"},
        {"type": "image", "data": "T2", "label": "tile_0_1"},
        {"type": "image", "data": "T3", "label": "tile_1_0"},
        {"type": "image", "data": "T4", "label": "tile_1_1"},
    ]}]
    out = _normalize_vision_messages(msgs)
    m = out[0]
    assert m["images"] == ["T1", "T2", "T3", "T4"]
    for label in ("tile_0_0", "tile_0_1", "tile_1_0", "tile_1_1"):
        assert f"[image: {label}]" in m["content"]


def test_input_is_not_mutated():
    """Caller's message list must survive the call unchanged."""
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image", "data": "Z", "label": "image"},
    ]}]
    original_content = msgs[0]["content"]
    _ = _normalize_vision_messages(msgs)
    assert msgs[0]["content"] is original_content  # same list, untouched


def test_image_block_without_data_dropped():
    """Defensive: a malformed image block with no data shouldn't
    crash; it just doesn't contribute to images=."""
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "ok"},
        {"type": "image", "media_type": "image/png"},  # no data
    ]}]
    out = _normalize_vision_messages(msgs)
    assert out[0].get("images") in (None,)  # absent or empty
    assert out[0]["content"] == "ok"


def test_other_provider_block_shape_ignored():
    """An OpenAI image_url block accidentally fed to Ollama is
    ignored rather than crashing the call. vision_analyze's
    provider-shape picker should prevent this in practice."""
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,XX"}},
    ]}]
    out = _normalize_vision_messages(msgs)
    # text survives; the image_url block is dropped.
    assert out[0]["content"] == "describe"
    assert "images" not in out[0]


def test_assistant_message_with_text_content_unaffected():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello back"},
    ]
    out = _normalize_vision_messages(msgs)
    assert out == msgs


def test_end_to_end_vision_passthrough_to_ollama_shape(tmp_path):
    """Compose: passthrough_blocks(provider="ollama") → wrap as
    a user message → _normalize → assert Ollama shape."""
    from athena.vision.passthrough import passthrough_blocks
    from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures
    ensure_fixtures()

    blocks = passthrough_blocks(FIXTURES_DIR / "small.png", provider="ollama")
    assert blocks["tiled"] is False  # small image, single block

    content = [{"type": "text", "text": "Describe this image."}]
    content.extend(blocks["blocks"])
    msgs = [{"role": "user", "content": content}]

    out = _normalize_vision_messages(msgs)
    assert out[0]["role"] == "user"
    assert "Describe this image." in out[0]["content"]
    assert len(out[0]["images"]) == 1
    # The base64 payload round-trips through Pillow → real image.
    import base64
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(out[0]["images"][0])))
    img.verify()
