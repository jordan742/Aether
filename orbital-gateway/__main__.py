"""Entry point: python -m orbital-gateway"""
import asyncio
from .gateway import OrbitalGateway

if __name__ == "__main__":
    asyncio.run(OrbitalGateway().run())
