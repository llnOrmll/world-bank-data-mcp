"""
World Bank Data360 MCP Server
Exposes World Bank API operations - Claude orchestrates the intelligence
"""

import requests
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
# FastMCP Server with Smithery
# ============================================================================

@smithery.server(config_schema=ConfigSchema)
def create_server():
    """Create World Bank Data MCP server"""
    server = FastMCP(name="world-bank-data")
    
    @server.tool()
    def search_datasets_tool(search_query: str, top: int = 20) -> dict[str, Any]:
        """Search World Bank Data360 for datasets. This is STEP 1 of 3 in the data retrieval workflow.
        
        Find indicator IDs and database IDs needed for subsequent data operations.
        
        Optimization tips:
        - Remove punctuation: "GDP, total" becomes "GDP total"
        - Expand abbreviations: "GDP" becomes "Gross Domestic Product"
        - Add "total" for aggregates: "population" becomes "population total"
        - Use lowercase for consistency
        - Remove filler words: "data", "statistics"
        
        Common databases:
        - WB_WDI: World Development Indicators (most comprehensive)
        - WB_HNP: Health, Nutrition and Population
        - WB_GDF: Global Development Finance
        
        Returns: List of datasets with indicator IDs, names, database IDs, and search scores.
        Next step: Call get_temporal_coverage with the indicator and database from results.
        """
        return search_datasets(search_query, top)
    
    @server.tool()
    def get_temporal_coverage_tool(indicator: str, database: str) -> dict[str, Any]:
        """Get available years for a specific dataset. STEP 2 of 3.
        
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
        year: str | None = None,
        countries: str | None = None,
        sex: str | None = None,
        age: str | None = None,
        limit: int = 20,
        sort_order: str = "desc",
        exclude_aggregates: bool = True,
        compact_response: bool = True
    ) -> dict[str, Any]:
        """Retrieve actual data from World Bank Data360. STEP 3 of 3.
        
        PREREQUISITE: Call get_temporal_coverage first to get latest_year.
        
        Parameters:
        - indicator: Indicator ID (from search_datasets)
        - database: Database ID (from search_datasets)
        - year: Specific year (e.g., '2023')
        - countries: Comma-separated ISO codes (e.g., 'USA,CHN,JPN')
        - sex: Gender filter: 'M' or 'F' or '_T' for total
        - age: Age group (varies by indicator)
        - limit: Return only top N records (default: 20)
        - sort_order: 'desc' or 'asc' (default: 'desc')
        - exclude_aggregates: Exclude regional/income aggregates (default: True)
        - compact_response: Return only essential fields (default: True)
        
        Returns: Data records with summary statistics.
        """
        return retrieve_data(
            indicator, database, year, countries, sex, age,
            limit, sort_order, exclude_aggregates, compact_response
        )
    
    return server

# For local development with smithery CLI
def main():
    """Entry point for local development"""
    return create_server()
