"""Entry point: python -m equity-bot"""
import asyncio
from .bot import EquityBot

if __name__ == "__main__":
    asyncio.run(EquityBot().run())
