"""
World Bank Data360 MCP Server
Exposes World Bank API operations - Claude orchestrates the intelligence
"""

import asyncio
import json
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import requests
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

app = Server("world-bank-data360")


# ============================================================================
# Tool Arguments
# ============================================================================

class SearchDatasetsArgs(BaseModel):
    """Search for datasets in World Bank Data360"""
    search_query: str = Field(
        description="Search term. Use enhanced keywords (e.g., 'poverty total', 'gross domestic product total')"
    )
    top: int = Field(default=20, description="Number of results (1-100)")


class GetTemporalCoverageArgs(BaseModel):
    """Get available years for a dataset"""
    indicator: str = Field(description="Indicator ID (idno) from search results")
    database: str = Field(description="Database ID from search results")


class RetrieveDataArgs(BaseModel):
    """Retrieve actual data from World Bank"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True)

    indicator: str = Field(description="Indicator ID (idno)")
    database: str = Field(description="Database ID")
    year: str | None = Field(default=None, description="Specific year (e.g., '2024')")
    countries: str | None = Field(default=None, description="Comma-separated ISO alpha-3 codes (e.g., 'USA,CHN,JPN')")
    sex: str | None = Field(default=None, description="Gender filter: 'M' or 'F' or '_T' for total")
    age: str | None = Field(default=None, description="Age group (varies by indicator)")
    # Accept str | int | None in schema to allow MCP protocol flexibility, then normalize to int
    limit: str | int | None = Field(default=20, description="CLIENT-SIDE: Return only top N records after sorting (default: 20)")
    sort_order: str = Field(default="desc", description="CLIENT-SIDE: Sort by OBS_VALUE - 'desc' or 'asc'")
    exclude_aggregates: bool = Field(default=True, description="CLIENT-SIDE: Exclude regional/income aggregates, keep only countries")
    compact_response: bool = Field(default=True, description="CLIENT-SIDE: Return only essential fields (country, year, value) to minimize tokens. Set to false for all fields.")

    @field_validator('limit', mode='before')
    @classmethod
    def coerce_limit_to_int(cls, v):
        """Coerce string/int to int for consistent processing"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"limit must be an integer, got: {v}")
        if isinstance(v, int):
            return v
        raise ValueError(f"limit must be an integer or string integer, got type: {type(v)}")


# ============================================================================
# Core Functions
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
    limit: int | None = None,
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
# MCP Tool Registration
# ============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available World Bank tools"""
    return [
        Tool(
            name="search_datasets",
            description="""<purpose>
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
</next_step>""",
            inputSchema=SearchDatasetsArgs.model_json_schema()
        ),
        
        Tool(
            name="get_temporal_coverage",
            description="""[STEP 2/3] Get available years for a specific dataset.

⚠️ CRITICAL: Always call this BEFORE retrieve_data to avoid errors.

📋 OPTIMAL WORKFLOW:
1. search_datasets - Done ✓
2. get_temporal_coverage (this tool) - Check what years are available
3. retrieve_data - Use latest_year from this response

Required parameters:
- indicator: Indicator ID from search_datasets results
- database: Database ID from search_datasets results

Returns: start_year, end_year, latest_year, and full list of available years.
Next step: Call retrieve_data with year=latest_year.""",
            inputSchema=GetTemporalCoverageArgs.model_json_schema()
        ),
        
        Tool(
            name="retrieve_data",
            description="""[STEP 3/3] Retrieve actual data from World Bank Data360.

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
- Show indicator name as title

Returns: Data records + summary.""",
            inputSchema=RetrieveDataArgs.model_json_schema()
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls"""
    
    if name == "search_datasets":
        args = SearchDatasetsArgs(**arguments)
        result = search_datasets(args.search_query, args.top)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "get_temporal_coverage":
        args = GetTemporalCoverageArgs(**arguments)
        result = get_temporal_coverage(args.indicator, args.database)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "retrieve_data":
        args = RetrieveDataArgs(**arguments)
        result = retrieve_data(
            args.indicator,
            args.database,
            args.year,
            args.countries,
            args.sex,
            args.age,
            args.limit,
            args.sort_order,
            args.exclude_aggregates,
            args.compact_response
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())