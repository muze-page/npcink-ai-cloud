from __future__ import annotations

import httpx

from app.adapters.recognition.siliconflow import SiliconFlowRecognitionEvidenceImporter


def test_siliconflow_importer_fetches_recognition_evidence_from_public_pricing_page() -> None:
    html = """
<!DOCTYPE html>
<html>
  <body>
    <div class="h-[43px] px-[12px] flex items-center"><div class="flex-1"><a href="https://cloud.siliconflow.cn/models?target=Qwen/Qwen3.5-4B" target="_blank" class="hover:text-primary">Qwen/Qwen3.5-4B</a></div><div class="flex-1">免费</div><div class="flex-1">免费</div></div>
    <div class="h-[43px] px-[12px] flex items-center"><div class="flex-1"><a href="https://cloud.siliconflow.cn/models?target=Qwen/Qwen-Image" target="_blank" class="hover:text-primary">Qwen/Qwen-Image</a></div><div class="flex-1">0.72</div><div class="flex-1">2.16</div></div>
    <script>
      self.__next_f.push([1,"\\\"DisplayName\\\":\\\"Qwen3.5-4B\\\",\\\"contextLen\\\":262144,\\\"type\\\":\\\"text\\\",\\\"subType\\\":\\\"chat\\\",\\\"jsonModeSupport\\\":true,\\\"functionCallSupport\\\":true,\\\"vlm\\\":false,\\\"targetModelName\\\":\\\"Qwen/Qwen3.5-4B\\\""])
      self.__next_f.push([1,"\\\"DisplayName\\\":\\\"Qwen-Image\\\",\\\"type\\\":\\\"image\\\",\\\"subType\\\":\\\"text-to-image\\\",\\\"jsonModeSupport\\\":false,\\\"functionCallSupport\\\":false,\\\"vlm\\\":false,\\\"targetModelName\\\":\\\"Qwen/Qwen-Image\\\""])
    </script>
  </body>
</html>
""".strip()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www2.siliconflow.cn/pricing"
        return httpx.Response(
            200,
            headers={"etag": "siliconflow-pricing-rev-001"},
            text=html,
        )

    importer = SiliconFlowRecognitionEvidenceImporter(
        pricing_url="https://www2.siliconflow.cn/pricing",
        cny_per_usd=7.2,
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    chat = payload["records"]["siliconflow::Qwen/Qwen3.5-4B"]
    image = payload["records"]["siliconflow::Qwen/Qwen-Image"]

    assert payload["version"] == "recognition_upstream_v1"
    assert payload["sources"]["siliconflow_snapshot"] == "siliconflow-pricing-rev-001"
    assert chat["model_type"] == "chat"
    assert chat["price_input"] == 0.0
    assert chat["price_output"] == 0.0
    assert chat["capabilities"]["tools"] is True
    assert chat["capabilities"]["structured_output"] is True
    assert image["model_type"] == "image_generation"
    assert image["price_input"] == 0.1
    assert image["price_output"] == 0.3
    assert image["source_details"]["siliconflow_pricing_page"]["price_source"] == "siliconflow_pricing_page_cny"


def test_siliconflow_importer_raises_for_unparseable_pricing_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="<html><body>empty</body></html>")

    importer = SiliconFlowRecognitionEvidenceImporter(
        transport=httpx.MockTransport(handler),
    )

    try:
        importer.fetch_upstream_evidence_payload()
    except ValueError as error:
        assert "no parseable model rows" in str(error)
    else:
        raise AssertionError("expected invalid pricing payload to raise ValueError")
