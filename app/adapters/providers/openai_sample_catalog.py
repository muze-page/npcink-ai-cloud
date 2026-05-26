from __future__ import annotations

from app.adapters.providers.base import CatalogInstanceSeed, CatalogModelSeed


def build_recognition_sample_catalog() -> list[CatalogModelSeed]:
    return [
        CatalogModelSeed(
            model_id="flux-dev",
            family="flux",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-to-image", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-image-flux-dev",
                    endpoint_variant="images",
                    region="us-east",
                    capability_tags=["image", "generation", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="flux-schnell",
            family="flux",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-to-image", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-image-flux-schnell",
                    endpoint_variant="images",
                    region="us-east",
                    capability_tags=["image", "generation", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sdxl-turbo",
            family="stable-diffusion",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-to-image", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-image-sdxl-turbo",
                    endpoint_variant="images",
                    region="us-east",
                    capability_tags=["image", "generation", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="llava:13b",
            family="llava",
            feature="text",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "image-text-to-text", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-vision-llava-13b",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["vision", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="qwen2.5-vl-7b-instruct",
            family="qwen-vl",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "image-text-to-text", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-vision-qwen25vl-7b",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["vision", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="minicpm-v-2.6",
            family="minicpm-v",
            feature="text",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "visual-question-answering", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-vision-minicpm-v-26",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["vision", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="bge-m3",
            family="bge",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-embedding", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-embed-bge-m3",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="multilingual-e5-large",
            family="e5",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "sentence-similarity", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-embed-multilingual-e5-large",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="gte-large-en-v1.5",
            family="gte",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-embedding", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-embed-gte-large-en-v15",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="mistral-small-3.1",
            family="mistral",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-text-mistral-small-31",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["text", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="gemma-3-27b-it",
            family="gemma",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-text-gemma-3-27b-it",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["text", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="deepseek-r1-distill-qwen-32b",
            family="deepseek",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-text-deepseek-r1-distill-qwen-32b",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["text", "reasoning", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="qwen2.5-72b-instruct",
            family="qwen",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-text-qwen25-72b-instruct",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["text", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="jina-embeddings-v3",
            family="jina-embeddings",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "feature-extraction", "catalog_profile": "recognition_sample"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-embed-jina-embeddings-v3",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
    ]


def build_scaled_recognition_review_catalog(*, total_models: int) -> list[CatalogModelSeed]:
    if total_models <= 3:
        return []

    named_models = build_recognition_sample_catalog()
    target_sample_models = total_models - 3
    if target_sample_models <= len(named_models):
        return named_models[:target_sample_models]

    scaled_models = list(named_models)
    generated_models_needed = target_sample_models - len(named_models)
    archetypes = _build_scaled_recognition_archetypes()
    generated_count = 0
    variant_index = 1

    while generated_count < generated_models_needed:
        for archetype in archetypes:
            if generated_count >= generated_models_needed:
                break
            scaled_models.append(_clone_scaled_sample_model(archetype, variant_index))
            generated_count += 1
        variant_index += 1

    return scaled_models


def _build_scaled_recognition_archetypes() -> list[CatalogModelSeed]:
    return [
        CatalogModelSeed(
            model_id="sample-chat-balanced",
            family="sample-chat",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-chat-balanced",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["text", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-chat-reasoning",
            family="sample-reasoning",
            feature="text",
            status="available",
            context_window=65536,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-chat-reasoning",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["text", "reasoning", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-vision-vqa",
            family="sample-vision",
            feature="text",
            status="available",
            context_window=16384,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={
                "pipeline_tag": "image-text-to-text",
                "catalog_profile": "recognition_review_scaled",
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-vision-vqa",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["vision", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-vision-doc",
            family="sample-vision",
            feature="text",
            status="available",
            context_window=16384,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={
                "pipeline_tag": "visual-question-answering",
                "catalog_profile": "recognition_review_scaled",
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-vision-doc",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["vision", "ocr", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-image-flux",
            family="sample-image",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-to-image", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-image-flux",
                    endpoint_variant="images",
                    region="us-east",
                    capability_tags=["image", "generation", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-image-sd",
            family="sample-image",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-to-image", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-image-sd",
                    endpoint_variant="images",
                    region="us-east",
                    capability_tags=["image", "generation", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-embed-bge",
            family="sample-embedding",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-embedding", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-embed-bge",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-embed-e5",
            family="sample-embedding",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={
                "pipeline_tag": "sentence-similarity",
                "catalog_profile": "recognition_review_scaled",
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-embed-e5",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-code-chat",
            family="sample-code",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-code-chat",
                    endpoint_variant="chat_completions",
                    region="us-east",
                    capability_tags=["text", "code", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-math-reasoning",
            family="sample-math",
            feature="text",
            status="available",
            context_window=65536,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={"pipeline_tag": "text-generation", "catalog_profile": "recognition_review_scaled"},
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-math-reasoning",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["text", "reasoning", "math", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-multimodal-chat",
            family="sample-multimodal",
            feature="text",
            status="available",
            context_window=32768,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={
                "pipeline_tag": "image-text-to-text",
                "catalog_profile": "recognition_review_scaled",
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-multimodal-chat",
                    endpoint_variant="responses",
                    region="us-east",
                    capability_tags=["vision", "chat", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
        CatalogModelSeed(
            model_id="sample-reranker",
            family="sample-reranker",
            feature="embedding",
            status="available",
            context_window=8192,
            price_input=0.0,
            price_output=0.0,
            fallback_candidate=False,
            raw_json={
                "pipeline_tag": "feature-extraction",
                "catalog_profile": "recognition_review_scaled",
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id="openai-us-east-sample-reranker",
                    endpoint_variant="embeddings",
                    region="us-east",
                    capability_tags=["embedding", "reranker", "sample", "scaled"],
                    is_default=True,
                    weight=100,
                )
            ],
        ),
    ]


def _clone_scaled_sample_model(model: CatalogModelSeed, variant_index: int) -> CatalogModelSeed:
    suffix = f"-{variant_index:03d}"
    raw_json = dict(model.raw_json)
    raw_json["catalog_profile"] = "recognition_review_scaled"
    raw_json["catalog_profile_variant_index"] = variant_index
    raw_json["catalog_profile_variant"] = f"{model.model_id}{suffix}"
    instances = [
        CatalogInstanceSeed(
            instance_id=f"{instance.instance_id}{suffix}",
            endpoint_variant=instance.endpoint_variant,
            region=instance.region,
            capability_tags=list(instance.capability_tags),
            is_default=instance.is_default,
            weight=instance.weight,
        )
        for instance in model.instances
    ]
    return CatalogModelSeed(
        model_id=f"{model.model_id}{suffix}",
        family=model.family,
        feature=model.feature,
        status=model.status,
        context_window=model.context_window,
        price_input=model.price_input,
        price_output=model.price_output,
        fallback_candidate=model.fallback_candidate,
        raw_json=raw_json,
        instances=instances,
    )
