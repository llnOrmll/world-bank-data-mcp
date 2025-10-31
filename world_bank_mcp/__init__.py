#!/usr/bin/env python
"""Entry point for World Bank MCP Server"""

import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())