"""
World Bank Data360 MCP Server
Exposes World Bank API operations via FastMCP for Smithery
"""

import requests
from typing import Any
from mcp.server.fastmcp import FastMCP, Context
from smithery.decorators import smithery
from pydantic import BaseModel, Field, field_validator

# API Configuration
DATA360_BASE_URL = "https://data360api.worldbank.org"
SEARCH_ENDPOINT = f"{DATA360_BASE_URL}/data360/searchv2"
DATA_ENDPOINT = f"{DATA360_BASE_URL}/data360/data"
METADATA_ENDPOINT = f"{DATA360_BASE_URL}/data360/metadata"

# Regional and income group aggregates
AGGREGATE_CODES = {
    "AFE", "AFW", "ARB", "CEB", "CSS", "EAP", "EAR", "EAS", "ECA", "ECS", "EMU", "EUU",
    "FCS", "HIC", "HPC", "IBD", "IBT", "IDA", "IDB", "IDX", "INX", "LAC",
    "LCN", "LDC", "LIC", "LMC", "LMY", "LTE", "MEA", "MIC", "MNA", "NAC",
    "OED", "OSS", "PRE", "PSS", "PST", "SAS", "SSA", "SSF", "SST", "TEA",
    "TEC", "TLA", "TMN", "TSA", "TSS", "UMC", "WLD"
}


class ConfigSchema(BaseModel):
    """No configuration needed for this server"""
    pass


@smithery.server(config_schema=ConfigSchema)
def create_server():
    """Create World Bank Data MCP server"""
    server = FastMCP(name="world-bank-data")
    
    @server.tool()
    def search_datasets(search_query: str, top: int = 20) -> dict[str, Any]:
        """Search World Bank Data360 for datasets. STEP 1 of 3 in workflow."""
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
    
    @server.tool()
    def get_temporal_coverage(indicator: str, database: str) -> dict[str, Any]:
        """Get available years for a dataset. STEP 2 of 3 - call before retrieve_data."""
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
    
    @server.tool()
    def retrieve_data(
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
        """Retrieve actual data from World Bank. STEP 3 of 3."""
        
        params = {
            "DATABASE_ID": database,
            "INDICATOR": indicator,
            "skip": 0,
        }

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

            if exclude_aggregates and all_data:
                all_data = [d for d in all_data if d.get("REF_AREA") not in AGGREGATE_CODES]

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
                    return {
                        "success": False,
                        "error": f"Sorting failed: {str(e)}"
                    }

            display_data = all_data[:limit] if limit else all_data

            unique_countries = set(d.get("REF_AREA") for d in display_data if d.get("REF_AREA"))
            unique_years = sorted(set(d.get("TIME_PERIOD") for d in display_data if d.get("TIME_PERIOD")))

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
    
    return server