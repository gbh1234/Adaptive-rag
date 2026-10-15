import asyncio

from app.config.settings import get_settings
from app.providers.embeddings import build_embedding_provider
from app.retrieval.ingest import KnowledgeIngestor


async def main() -> None:
    settings = get_settings()
    embedder = build_embedding_provider(settings)
    chunks, records = await KnowledgeIngestor(
        settings.knowledge_dir, embedder, settings=settings
    ).load()
    print(f"ingested chunks={len(chunks)} vectors={len(records)}")


if __name__ == "__main__":
    asyncio.run(main())
