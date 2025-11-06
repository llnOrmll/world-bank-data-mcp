# World Bank Data360 MCP Server

Search 1,000+ World Bank economic and social indicators for 200+ countries. Filter by year, country, and demographics to access 60+ years of historical data. Compare results to surface the latest figures and trends.

MCP server that exposes World Bank Data360 OPEN API to Claude Desktop.

## Features

- 🔍 Search 1000+ economic and social indicators
- 📊 Access data for 200+ countries
- 📅 Historical data spanning 60+ years
- 🌍 Filter by country, year, demographics

## Installation

```bash
# Clone or download this repository
cd world-bank-mcp

# Install dependencies
uv sync
```

## Quick Test

```bash
# Test the server starts correctly
uv run python -m world_bank_mcp
```

## Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "world-bank-data": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/world-bank-mcp",
        "run",
        "python",
        "-m",
        "world_bank_mcp"
      ]
    }
  }
}
```

**Important**: Replace `/absolute/path/to/world-bank-mcp` with your actual path.

Then **restart Claude Desktop** to load the server.

## Usage Examples

This MCP server enables natural language queries about World Bank data. Simply ask Claude, and it will automatically handle the 3-step workflow (search → check years → retrieve data).

### 📊 Economic Indicators

**GDP Comparisons**
```
"Compare GDP per capita for USA, China, Japan, Germany, and UK over the last 5 years"
"Show me the top 10 countries by GDP in 2023"
"What was India's GDP growth rate from 2015 to 2023?"
```

**Inflation & Monetary**
```
"Show inflation rates for G7 countries in 2023"
"Compare inflation trends for Argentina, Turkey, and Venezuela"
```

**Trade & Investment**
```
"What are China's exports and imports for 2023?"
"Show foreign direct investment flows to Brazil"
```

### 👥 Demographics & Social

**Population Statistics**
```
"Show me the top 20 most populous countries"
"What's the population growth rate for African countries?"
"Compare urban population percentage across continents"
```

**Life Expectancy & Health**
```
"Show life expectancy at birth for Nordic countries"
"Compare infant mortality rates between developed and developing nations"
"What's the maternal mortality rate trend in Sub-Saharan Africa?"
```

### 🏥 Health & Education

**Healthcare Metrics**
```
"Show healthcare expenditure as % of GDP for OECD countries"
"Compare access to clean water across Southeast Asian countries"
```

**Education Indicators**
```
"Show literacy rates for countries in South Asia"
"Compare school enrollment rates (primary vs secondary vs tertiary)"
"What's the education expenditure as % of GDP for top performers?"
```

### 🌍 Environment & Energy

**Climate & Emissions**
```
"Compare CO2 emissions per capita for USA, China, India, and EU"
"Show renewable energy consumption trends for Scandinavian countries"
"What's the forest area percentage for Amazon basin countries?"
```

**Energy & Infrastructure**
```
"Compare electricity access rates across African countries"
"Show renewable vs fossil fuel energy mix for Germany"
```

### 💼 Labor & Employment

**Unemployment & Workforce**
```
"Show unemployment rates for European countries in 2023"
"Compare labor force participation rates by gender"
"What's the youth unemployment rate in Mediterranean countries?"
```

### 📈 Poverty & Inequality

**Poverty Metrics**
```
"Show poverty headcount ratio for countries below $3/day"
"Compare Gini index (income inequality) across Latin America"
"What's the income share held by the bottom 20% in Nordic countries?"
```

### 🔍 Discovery Queries

**Find Available Data**
```
"What unemployment-related indicators are available?"
"Show me all indicators related to renewable energy"
"List popular economic indicators I can query"
```

## How It Works

Claude will automatically:
1. 🔍 **Search** for the right dataset using optimized keywords
2. 📅 **Check** available years to use the latest data
3. 📊 **Retrieve** data with proper filters (country, year, demographics)
4. 📋 **Format** results as tables with rankings and trends

No need to know indicator codes or database IDs - just ask in natural language!

## Available Tools

### Core Tools (3-Step Workflow)

#### 1. `search_datasets`
Search World Bank Data360 API for datasets by keywords.

**Tip**: Use optimized queries like "gross domestic product total" instead of "GDP data"

#### 2. `get_temporal_coverage`
Get available years for a specific dataset before retrieving data.

**Why**: Ensures you request valid years and avoid errors

#### 3. `retrieve_data`
Retrieve actual data with filters (year, countries, demographics).

**Features**:
- Filter by country, year, sex, age
- Sort and limit results
- Exclude regional aggregates (default: true)
- Compact response mode (saves 75% tokens)

### Discovery Tools (Find What's Available)

#### 4. `list_popular_indicators`
Get a curated list of 38 commonly-requested indicators organized by category.

**Categories**: Demographics, Economy, Health, Education, Labor, Poverty, Environment, Infrastructure, Technology

**When to use**: "What data is available?" or "Show me popular indicators"

#### 5. `search_local_indicators`
Instantly search through 1,500+ indicators locally (no API call).

**Features**:
- Searches names AND descriptions
- Instant, offline results
- Relevance-ranked matches

**When to use**: "What unemployment indicators are available?" or "Find all water-related data"

## Data Sources

- **WB_WDI**: World Development Indicators
- **WB_HNP**: Health, Nutrition & Population Statistics
- **WB_GDF**: Global Development Finance
- **WB_IDS**: International Debt Statistics

## Common Country Codes

USA, CHN, JPN, DEU, GBR, FRA, IND, BRA, RUS, CAN, KOR, AUS, MEX, IDN, TUR, SAU, ARG, ZAF, ITA, ESP

## License

MIT
