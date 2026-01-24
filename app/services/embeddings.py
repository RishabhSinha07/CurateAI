"""
Embeddings service using AWS Bedrock Titan v2.
"""

import json
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

settings = get_settings()

# Configure boto3 client with retries
_bedrock_config = Config(
    region_name=settings.aws_region,
    retries={"max_attempts": 3, "mode": "adaptive"},
)

_bedrock_client: "BedrockRuntimeClient | None" = None


def get_bedrock_client() -> "BedrockRuntimeClient":
    """Get or create Bedrock runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            config=_bedrock_config,
        )
    return _bedrock_client


def generate_embedding(text: str) -> list[float]:
    """
    Generate embedding for a single text using AWS Bedrock Titan v2.

    Args:
        text: The text to embed.

    Returns:
        List of floats representing the embedding vector (1024 dimensions).
    """
    client = get_bedrock_client()

    # Titan v2 request format
    request_body = json.dumps({
        "inputText": text,
        "dimensions": settings.embedding_dimensions,  # 1024
        "normalize": True,  # Normalize for cosine similarity
    })

    response = client.invoke_model(
        modelId=settings.embedding_model_id,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())
    return response_body["embedding"]


def generate_embeddings_batch(texts: list[str], batch_size: int = 10) -> list[list[float]]:
    """
    Generate embeddings for multiple texts.

    Note: Titan v2 doesn't support native batching, so we process sequentially.
    For large batches, consider using async/concurrent processing.

    Args:
        texts: List of texts to embed.
        batch_size: Not used currently (kept for API compatibility).

    Returns:
        List of embedding vectors.
    """
    embeddings = []
    for text in texts:
        embedding = generate_embedding(text)
        embeddings.append(embedding)
    return embeddings


async def generate_embedding_async(text: str) -> list[float]:
    """
    Async wrapper for embedding generation.

    Note: boto3 is synchronous, so this runs in a thread pool.
    For true async, consider using aioboto3.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, generate_embedding, text)


async def generate_embeddings_batch_async(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts asynchronously.
    """
    import asyncio
    tasks = [generate_embedding_async(text) for text in texts]
    return await asyncio.gather(*tasks)
