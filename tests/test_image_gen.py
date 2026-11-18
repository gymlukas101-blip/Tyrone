import base64
import json

import httpx

from monkey.integrations.image_gen import estimate_cost, generate

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def client(calls):
    def handler(req: httpx.Request):
        calls.append(req)
        return httpx.Response(200, json={"data": [{"b64_json": PNG}, {"b64_json": PNG}],
                                         "usage": {"input_tokens": 1000, "output_tokens": 6000,
                                                   "input_tokens_details": {"image_tokens": 900, "text_tokens": 100}}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generations_request_and_files(tmp_path):
    calls = []
    res = generate("a banana spaceship", tmp_path, n=2, api_key="sk-test", client=client(calls), name="ship")
    req = calls[0]
    assert req.url.path == "/v1/images/generations" and req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "gpt-image-2.6-sunburst" and body["n"] == 2 and body["quality"] == "high"
    assert [p.name for p in res.paths] == ["ship-1.png", "ship-2.png"] and res.paths[0].read_bytes().startswith(b"\x89PNG")
    assert round(res.cost_usd, 4) == round((100 * 5 + 900 * 8 + 6000 * 30) / 1e6, 4)


def test_edits_with_reference_and_no_key(tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"jpg")
    calls = []
    generate("same character waving", tmp_path / "out", refs=[ref], client=client(calls), model="gpt-image-2.6-flare")
    req = calls[0]
    assert req.url.path == "/v1/images/edits" and "authorization" not in req.headers
    text = req.content.decode("latin-1")
    assert 'name="image[]"; filename="ref.jpg"' in text and "image/jpeg" in text and "gpt-image-2.6-flare" in text


def test_errors_raise(tmp_path):
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "nope"}})))
    try:
        generate("x", tmp_path, client=bad)
    except RuntimeError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected error")


def test_cost_estimate_defaults():
    assert estimate_cost({}) == 0
