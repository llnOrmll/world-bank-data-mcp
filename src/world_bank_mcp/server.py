"""
World Bank Data360 MCP Server
Exposes World Bank API operations - Claude orchestrates the intelligence
"""

import json
import requests
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from smithery.decorators import smithery
from pydantic import BaseModel, Field, ConfigDict, field_validator

# API Configuration
DATA360_BASE_URL = "https://data360api.worldbank.org"
SEARCH_ENDPOINT = f"{DATA360_BASE_URL}/data360/searchv2"
DATA_ENDPOINT = f"{DATA360_BASE_URL}/data360/data"
METADATA_ENDPOINT = f"{DATA360_BASE_URL}/data360/metadata"

# Regional and income group aggregates (not individual countries)
AGGREGATE_CODES = {
    "AFE", "AFW", "ARB", "CEB", "CSS", "EAP", "EAR", "EAS", "ECA", "ECS", "EMU", "EUU",
    "FCS", "HIC", "HPC", "IBD", "IBT", "IDA", "IDB", "IDX", "INX", "LAC",
    "LCN", "LDC", "LIC", "LMC", "LMY", "LTE", "MEA", "MIC", "MNA", "NAC",
    "OED", "OSS", "PRE", "PSS", "PST", "SAS", "SSA", "SSF", "SST", "TEA",
    "TEC", "TLA", "TMN", "TSA", "TSS", "UMC", "WLD"
}


# ============================================================================
# Configuration Schema
# ============================================================================

class ConfigSchema(BaseModel):
    """No configuration needed for this server"""
    pass


# ============================================================================
# Core Functions (unchanged)
# ============================================================================

def search_datasets(search_query: str, top: int = 20) -> dict[str, Any]:
    """Search World Bank Data360 API"""
    payload = {
        "count": True,
        "select": "series_description/idno, series_description/name, series_description/database_id",
        "search": search_query,
        "top": top,
    }

    try:
        response = requests.post(
            SEARCH_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        
        # Format results nicely
        results = []
        for item in data.get("value", []):
            series = item.get("series_description", {})
            results.append({
                "indicator": series.get("idno"),
                "name": series.get("name"),
                "database": series.get("database_id"),
                "search_score": round(item.get("@search.score", 0), 2)
            })
        
        return {
            "success": True,
            "total_count": data.get("@odata.count", 0),
            "results": results
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_temporal_coverage(indicator: str, database: str) -> dict[str, Any]:
    """Get available years for a dataset"""
    try:
        payload = {
            "query": f"&$filter=series_description/idno eq '{indicator}'"
        }
        
        response = requests.post(
            METADATA_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        
        metadata = response.json()
        values = metadata.get("value", [])
        
        if not values:
            return {"success": False, "error": "No metadata found"}
        
        series_desc = values[0].get("series_description", {})
        time_periods = series_desc.get("time_periods", [])
        
        if time_periods:
            period = time_periods[0]
            start_year = int(period.get("start", 0))
            end_year = int(period.get("end", 0))
            
            return {
                "success": True,
                "start_year": start_year,
                "end_year": end_year,
                "latest_year": end_year,
                "available_years": list(range(start_year, end_year + 1))
            }
        
        return {"success": False, "error": "No temporal data available"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def retrieve_data(
    indicator: str,
    database: str,
    year: str | None = None,
    countries: str | None = None,
    sex: str | None = None,
    age: str | None = None,
    limit: int | None = 20,
    sort_order: str = "desc",
    exclude_aggregates: bool = True,
    compact_response: bool = True
) -> dict[str, Any]:
    """Retrieve actual data from World Bank API"""
    
    params = {
        "DATABASE_ID": database,
        "INDICATOR": indicator,
        "skip": 0,
    }

    # Apply filters
    if year:
        params["timePeriodFrom"] = year
        params["timePeriodTo"] = year
    
    if countries:
        params["REF_AREA"] = countries
    
    if sex:
        params["SEX"] = sex
    
    if age:
        params["AGE"] = age

    all_data = []

    try:
        # Pagination loop (max 10000 records as safety limit)
        while len(all_data) < 10000:
            response = requests.get(
                DATA_ENDPOINT,
                params=params,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            values = data.get("value", [])

            if not values:
                break

            all_data.extend(values)

            total_count = data.get("count", 0)
            if len(all_data) >= total_count:
                break

            params["skip"] = len(all_data)

        # CLIENT-SIDE: Filter out regional/income aggregates if requested
        if exclude_aggregates and all_data:
            all_data = [d for d in all_data if d.get("REF_AREA") not in AGGREGATE_CODES]

        # CLIENT-SIDE: Sort by OBS_VALUE if requested
        if all_data and sort_order:
            data_with_values = [d for d in all_data if d.get("OBS_VALUE") is not None]
            data_without_values = [d for d in all_data if d.get("OBS_VALUE") is None]

            reverse_order = (sort_order.lower() == "desc")
            try:
                sorted_data = sorted(
                    data_with_values,
                    key=lambda x: float(str(x.get("OBS_VALUE", "0"))),
                    reverse=reverse_order
                )
                all_data = sorted_data + data_without_values
            except (ValueError, TypeError) as e:
                # If sorting fails, return error in response
                return {
                    "success": False,
                    "error": f"Sorting failed: {str(e)}. OBS_VALUE type: {type(data_with_values[0].get('OBS_VALUE')) if data_with_values else 'no data'}"
                }

        # CLIENT-SIDE: Apply limit to reduce tokens sent to Claude
        display_data = all_data[:limit] if limit else all_data

        # Generate summary (before compacting to preserve field names)
        unique_countries = set(d.get("REF_AREA") for d in display_data if d.get("REF_AREA"))
        unique_years = sorted(set(d.get("TIME_PERIOD") for d in display_data if d.get("TIME_PERIOD")))

        # CLIENT-SIDE: Compact response to minimize tokens (only essential fields)
        if compact_response and display_data:
            display_data = [
                {
                    "country": d.get("REF_AREA"),
                    "country_name": d.get("REF_AREA_label"),
                    "year": d.get("TIME_PERIOD"),
                    "value": d.get("OBS_VALUE"),
                }
                for d in display_data
            ]

        return {
            "success": True,
            "record_count": len(display_data),
            "total_available": len(all_data),
            "data": display_data,
            "summary": {
                "countries": len(unique_countries),
                "years": unique_years,
                "applied_filters": {
                    "year": year,
                    "countries": countries,
                    "sex": sex,
                    "age": age
                }
            }
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Metadata Loading (Local Search)
# ============================================================================

# Cache for loaded metadata (singleton pattern)
_metadata_cache = None
_popular_cache = None

def load_metadata() -> list[dict[str, Any]]:
    """Load indicator metadata from JSON file (cached)"""
    global _metadata_cache

    if _metadata_cache is None:
        metadata_path = Path(__file__).parent / "metadata_indicators.json"
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _metadata_cache = data["indicators"]
        except Exception as e:
            # Return empty list if file not found or error
            _metadata_cache = []

    return _metadata_cache


def load_popular_indicators() -> list[dict[str, Any]]:
    """Load curated popular indicators from JSON file (cached)"""
    global _popular_cache

    if _popular_cache is None:
        popular_path = Path(__file__).parent / "popular_indicators.json"
        try:
            with open(popular_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _popular_cache = data["indicators"]
        except Exception as e:
            # Return empty list if file not found or error
            _popular_cache = []

    return _popular_cache


def search_local_metadata(query: str, limit: int = 20) -> dict[str, Any]:
    """Search through local metadata (fast, offline)"""
    indicators = load_metadata()

    if not indicators:
        return {
            "success": False,
            "error": "Metadata file not found. Please ensure metadata_indicators.json exists."
        }

    query_lower = query.lower()
    results = []

    # Search through indicators
    for indicator in indicators:
        name_lower = indicator["name"].lower()
        desc_lower = indicator["description"].lower()
        code_lower = indicator["code"].lower()

        # Calculate relevance score
        score = 0

        # Exact match in code (highest priority)
        if query_lower == code_lower:
            score = 100
        # Contains in code
        elif query_lower in code_lower:
            score = 90
        # Exact word match in name
        elif query_lower in name_lower.split():
            score = 80
        # Contains in name (high priority)
        elif query_lower in name_lower:
            score = 70
        # Contains in description (lower priority)
        elif query_lower in desc_lower:
            score = 40
        else:
            continue

        results.append({
            "indicator": indicator["code"],
            "name": indicator["name"],
            "description": indicator["description"][:200] + "..." if len(indicator["description"]) > 200 else indicator["description"],
            "source": indicator["source"][:100] + "..." if len(indicator["source"]) > 100 else indicator["source"],
            "relevance_score": score
        })

    # Sort by relevance score
    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    # Limit results
    results = results[:limit]

    return {
        "success": True,
        "query": query,
        "total_matches": len(results),
        "results": results,
        "note": "Local search - instant results from cached metadata"
    }


# ============================================================================
# FastMCP Server with Smithery
# ============================================================================

@smithery.server(config_schema=ConfigSchema)
def create_server():
    """Create World Bank Data MCP server"""
    server = FastMCP(name="world-bank-data")
    
    @server.tool()
    def search_datasets_tool(search_query: str, top: int = 20) -> dict[str, Any]:
        """[STEP 1/3] Search World Bank Data360 for datasets.
        <purpose>
            Search World Bank Data360 for datasets. This is STEP 1 of 3 in the data retrieval workflow.
            Find indicator IDs and database IDs needed for subsequent data operations.
        </purpose>

        <workflow>
            <step number="1">search_datasets (this tool) - Find indicator ID and database ID</step>
            <step number="2">get_temporal_coverage - Check available years BEFORE retrieving data</step>
            <step number="3">retrieve_data - Fetch actual data with proper year and limit parameters</step>
        </workflow>

        <optimization_tips>
            <tip>Remove punctuation: "GDP, total" becomes "GDP total"</tip>
            <tip>Expand abbreviations: "GDP" becomes "Gross Domestic Product"</tip>
            <tip>Add "total" for aggregates: "population" becomes "population total"</tip>
            <tip>Use lowercase for consistency</tip>
            <tip>Remove filler words: "data", "statistics"</tip>
        </optimization_tips>

        <common_databases>
            <database id="WB_WDI">World Development Indicators (most comprehensive)</database>
            <database id="WB_HNP">Health, Nutrition and Population</database>
            <database id="WB_GDF">Global Development Finance</database>
        </common_databases>

        <examples>
            <example original="GDP">gross domestic product total</example>
            <example original="population data">population total</example>
            <example original="">poverty headcount ratio</example>
        </examples>

        <returns>
            List of datasets with indicator IDs, names, database IDs, and search scores.
        </returns>

        <next_step>
            Call get_temporal_coverage with the indicator and database from results.
        </next_step>"""
        return search_datasets(search_query, top)
    
    @server.tool()
    def get_temporal_coverage_tool(indicator: str, database: str) -> dict[str, Any]:
        """[STEP 2/3] Get available years for a specific dataset.
        
        CRITICAL: Always call this BEFORE retrieve_data to avoid errors.
        
        Workflow:
        1. search_datasets - Done ✓
        2. get_temporal_coverage (this tool) - Check what years are available
        3. retrieve_data - Use latest_year from this response
        
        Returns: start_year, end_year, latest_year, and full list of available years.
        Next step: Call retrieve_data with year=latest_year.
        """
        return get_temporal_coverage(indicator, database)
    
    @server.tool()
    def retrieve_data_tool(
        indicator: str,
        database: str,
        year: str | int | None = None,
        countries: str | None = None,
        sex: str | None = None,
        age: str | None = None,
        limit: int = 20,
        sort_order: str = "desc",
        exclude_aggregates: bool = True,
        compact_response: bool = True
    ) -> dict[str, Any]:
        """[STEP 3/3] Retrieve actual data from World Bank Data360.

⚠️ PREREQUISITE: Call get_temporal_coverage first to get latest_year.

🚨 CRITICAL TYPE REQUIREMENTS 🚨

When calling this tool, you MUST pass parameters with the EXACT types shown below.
Common mistakes that cause validation errors:

❌ INCORRECT: {"limit": "10"}      ← limit as STRING (causes error!)
✅ CORRECT:   {"limit": 10}        ← limit as INTEGER

❌ INCORRECT: {"exclude_aggregates": "true"}    ← boolean as STRING
✅ CORRECT:   {"exclude_aggregates": true}      ← boolean as BOOLEAN

❌ INCORRECT: {"year": 2023}       ← year as NUMBER
✅ CORRECT:   {"year": "2023"}     ← year as STRING

📋 PARAMETER TYPES - MUST MATCH EXACTLY:

STRING parameters (use quotes in JSON):
  indicator: "WB_WDI_SP_POP_TOTL"
  database: "WB_WDI"
  year: "2023"
  countries: "USA,CHN,JPN"
  sex: "M" or "F" or "_T"
  age: "0-14"
  sort_order: "desc" or "asc"

INTEGER parameters (no quotes in JSON):
  limit: 10 (default: 20)

BOOLEAN parameters (no quotes in JSON):
  exclude_aggregates: true or false (default: true)
  compact_response: true or false (default: true)

🎯 CORRECT JSON EXAMPLES:

Example 1 - Top 10 countries by population:
{
  "indicator": "WB_WDI_SP_POP_TOTL",
  "database": "WB_WDI",
  "year": "2023",
  "limit": 10,
  "sort_order": "desc",
  "exclude_aggregates": true
}

Example 2 - Specific countries GDP:
{
  "indicator": "WB_WDI_NY_GDP_MKTP_CD",
  "database": "WB_WDI",
  "year": "2023",
  "countries": "USA,CHN,JPN"
}

Example 3 - All data with aggregates:
{
  "indicator": "WB_WDI_SP_POP_TOTL",
  "database": "WB_WDI",
  "year": "2022",
  "exclude_aggregates": false
}

⚡ HOW IT WORKS:
- countries parameter: API fetches ONLY those countries (efficient)
- exclude_aggregates: Filters out 47 regional/income codes (ARB, AFE, WLD, HIC, etc.)
  ⚠️ DEFAULT is TRUE - only individual countries returned
  Set to false to include aggregates like "World", "High income", "Arab World"
- sort_order: Sorts by OBS_VALUE before limiting
- limit parameter: Returns top N records to minimize tokens
  ⚠️ DEFAULT is 20 - provides reasonable default, override if you need more
- compact_response: Returns only essential fields (country, country_name, year, value)
  ⚠️ DEFAULT is TRUE - minimizes token usage by ~75%
  Set to false if you need all fields (REF_AREA, TIME_PERIOD, OBS_VALUE, UNIT_MEASURE, etc.)

📊 AFTER RECEIVING DATA:
Format results as markdown table:
- Sort by value (highest to lowest)
- Add rank numbers
- Format with thousand separators
- Include country names (not just codes)

Returns: Data records with summary statistics."""
        year_str = str(year) if year is not None else None

        return retrieve_data(
            indicator, database, year_str, countries, sex, age,
            limit, sort_order, exclude_aggregates, compact_response
        )

    @server.tool()
    def list_popular_indicators() -> dict[str, Any]:
        """Get a curated list of popular World Bank indicators.

        This tool helps users discover commonly requested indicators without searching.
        Perfect for getting started or exploring what data is available.

        Categories included:
        - Demographics: Population, growth rate, density, fertility
        - Economy: GDP, GDP per capita, growth, inflation, trade
        - Health: Life expectancy, mortality rates (infant, under-5, maternal)
        - Education: Literacy rates, school enrollment
        - Labor: Unemployment, labor force participation, employment ratios
        - Poverty & Inequality: Poverty rates, Gini index, income distribution
        - Environment: Greenhouse gas emissions, forest area, renewable energy
        - Infrastructure: Electricity access, water, sanitation
        - Technology: Internet usage, mobile subscriptions, broadband

        Returns: List of 38 curated indicators with codes, names, descriptions, and categories.

        Usage: Browse the list, pick an indicator code, then use search_datasets
        to find the exact database ID before retrieving data.
        """
        indicators = load_popular_indicators()

        if not indicators:
            return {
                "success": False,
                "error": "Popular indicators file not found. Please ensure popular_indicators.json exists."
            }

        # Group by category for better organization
        by_category = {}
        for ind in indicators:
            category = ind.get("category", "Other")
            if category not in by_category:
                by_category[category] = []
            by_category[category].append({
                "code": ind["code"],
                "name": ind["name"],
                "description": ind["description"][:150] + "..." if len(ind["description"]) > 150 else ind["description"]
            })

        return {
            "success": True,
            "total_indicators": len(indicators),
            "categories": list(by_category.keys()),
            "indicators_by_category": by_category,
            "note": "These are the most commonly requested indicators. Use search_local_indicators for more specific searches."
        }

    @server.tool()
    def search_local_indicators(query: str, limit: int = 20) -> dict[str, Any]:
        """Search through local metadata for World Bank indicators (instant, offline).

        This is a FAST alternative to search_datasets that searches through locally cached
        metadata. Use this to discover what types of data are available before using the
        API search.

        How it works:
        - Searches indicator names, codes, and descriptions
        - Instant results (no API call)
        - Returns relevance-ranked matches

        Search tips:
        - Use simple keywords: "unemployment", "poverty", "co2", "water"
        - Search works on indicator names AND descriptions
        - Case-insensitive
        - More specific queries = better results

        Example queries:
        - "unemployment" → finds all unemployment-related indicators
        - "mortality infant" → finds infant mortality indicators
        - "internet" → finds internet usage indicators
        - "renewable energy" → finds renewable energy indicators

        Parameters:
        - query: Search term (e.g., "unemployment", "gdp growth", "water access")
        - limit: Maximum number of results to return (default: 20)

        Returns: List of matching indicators with codes, names, descriptions, and relevance scores.

        Note: This returns indicator codes but NOT database IDs. After finding an indicator,
        use search_datasets with the indicator name to get the database ID needed for data retrieval.
        """
        return search_local_metadata(query, limit)

    return server

# For local development with smithery CLI
def main():
    """Entry point for local development"""
    server = create_server()
    server.run()  # This is synchronous and handles its own event loop

if __name__ == "__main__":
    main()
