"""Explicitly load sample products and orders into the configured database."""

import asyncio

from app.config.settings import get_settings
from app.repositories.db import create_engine, create_session_factory, init_schema
from app.services.seed import seed_demo_data


async def main() -> None:
    engine = create_engine(get_settings())
    try:
        await init_schema(engine)
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            await seed_demo_data(session)
    finally:
        await engine.dispose()
    print("Demo data ready for user u_demo (ORD10001–ORD10003).")


if __name__ == "__main__":
    asyncio.run(main())
