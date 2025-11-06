# World Bank Data360 MCP Server

[![smithery badge](https://smithery.ai/badge/@llnOrmll/world-bank-data-mcp)](https://smithery.ai/server/@llnOrmll/world-bank-data-mcp)

MCP server that exposes World Bank Data360 OPEN API to Claude Desktop.

## Features

- 🔍 Search 1000+ economic and social indicators
- 📊 Access data for 200+ countries
- 📅 Historical data spanning 60+ years
- 🌍 Filter by country, year, demographics

## Installation

```bash
cd /Users/llnormll/WorkSpace/world-bank-mcp

# Install dependencies
uv sync
```

## Test

```bash
uv run world_bank_mcp/server.py
```

## Claude Desktop Configuration

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "world-bank-data": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/world-bank-mcp",
        "run",
        "src/world_bank_mcp/server.py"
      ]
    }
  }
}
```

Restart Claude Desktop.

## Usage

Ask Claude:
- "Get world poverty data for 2024"
- "Show me GDP per capita for Japan in 2020"
- "Compare CO2 emissions for USA, China, and India"

Claude will automatically:
1. Search for the right dataset
2. Check available years
3. Retrieve the data with proper filters
4. Format and present results

## Available Tools

### 1. `search_datasets`
Search for datasets by keywords.

**Tip**: Use optimized queries like "gross domestic product total" instead of "GDP data"

### 2. `get_temporal_coverage`
Get available years for a specific dataset.

### 3. `retrieve_data`
Retrieve actual data with filters (year, countries, demographics).

## Data Sources

- **WB_WDI**: World Development Indicators
- **WB_HNP**: Health, Nutrition & Population Statistics
- **WB_GDF**: Global Development Finance
- **WB_IDS**: International Debt Statistics

## Common Country Codes

USA, CHN, JPN, DEU, GBR, FRA, IND, BRA, RUS, CAN, KOR, AUS, MEX, IDN, TUR, SAU, ARG, ZAF, ITA, ESP

## License

MIT