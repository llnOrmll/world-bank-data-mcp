# /// script
# dependencies = [
#   "python-dotenv",
#   "openai>=1.63.0",
#   "rich>=13.7.0",
#   "requests>=2.31.0",
#   "pydantic>=2.0.0",
# ]
# ///

"""
World Bank Data360 API Agent (Enhanced)
A smart agent that helps search and retrieve data from the World Bank Data360 API.
Enhanced with API scoring pattern optimizations.
"""

import os
import sys
import json
import argparse
from typing import List, Optional, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.json import JSON
import openai
import requests
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from parameter_extractor import extract_parameters, get_extracted_params_summary

load_dotenv()

# Initialize rich console
console = Console()

# API Configuration
DATA360_BASE_URL = "https://data360api.worldbank.org"
SEARCH_ENDPOINT = f"{DATA360_BASE_URL}/data360/searchv2"


# Pydantic Models for Tool Arguments
class SimpleSearchArgs(BaseModel):
    reasoning: str = Field(
        ..., description="Explanation for why this search is being performed"
    )
    search_query: str = Field(..., description="The search term or phrase to look for")
    top: int = Field(
        default=10, description="Number of results to return (1-100)", ge=1, le=100
    )


class AdvancedSearchArgs(BaseModel):
    reasoning: str = Field(..., description="Explanation for this advanced search")
    search_query: str = Field(..., description="The search term or phrase")
    select: str = Field(
        default="series_description/idno, series_description/name, series_description/database_id",
        description="Fields to return in results",
    )
    filter_query: Optional[str] = Field(
        None, description="OData filter expression (e.g., 'database_id eq WB_WDI')"
    )
    top: int = Field(default=10, description="Number of results", ge=1, le=100)
    count: bool = Field(default=True, description="Include total count in results")


class GetSearchSummaryArgs(BaseModel):
    reasoning: str = Field(
        ..., description="Why we need a summary of available search options"
    )


# Create tools list
tools = [
    openai.pydantic_function_tool(SimpleSearchArgs),
    openai.pydantic_function_tool(AdvancedSearchArgs),
    openai.pydantic_function_tool(GetSearchSummaryArgs),
]

AGENT_PROMPT = """<purpose>
    You are an expert at searching and retrieving data from the World Bank Data360 API.
    Your goal is to help users find the exact data they need using intelligent search strategies.
</purpose>

<instructions>
    <instruction>Start with simple searches to understand what data is available.</instruction>
    <instruction>Use advanced searches when you need to filter by specific databases or criteria.</instruction>
    <instruction>Always explain your reasoning for each search.</instruction>
    <instruction>If initial results don't match user needs, refine your search strategy.</instruction>
    <instruction>Present results in a clear, organized format.</instruction>
    <instruction>When you have found the data the user needs, summarize the findings.</instruction>
    <instruction>Use top={{recommended_top}} for the number of results to retrieve (more results for vague queries, fewer for specific queries).</instruction>
</instructions>

<available_tools>
    <tool>
        <name>SimpleSearchArgs</name>
        <description>Perform a basic keyword search across all Data360 metadata</description>
        <parameters>
            <parameter name="reasoning" type="string" required="true">Why this search is being performed</parameter>
            <parameter name="search_query" type="string" required="true">Keywords to search for</parameter>
            <parameter name="top" type="integer" required="false">Number of results (default: 10, max: 100)</parameter>
        </parameters>
    </tool>
    
    <tool>
        <name>AdvancedSearchArgs</name>
        <description>Perform an advanced search with filtering and field selection</description>
        <parameters>
            <parameter name="reasoning" type="string" required="true">Why this advanced search is needed</parameter>
            <parameter name="search_query" type="string" required="true">Keywords to search for</parameter>
            <parameter name="select" type="string" required="false">Comma-separated fields to return</parameter>
            <parameter name="filter_query" type="string" required="false">OData filter expression</parameter>
            <parameter name="top" type="integer" required="false">Number of results (default: 10)</parameter>
            <parameter name="count" type="boolean" required="false">Include total count (default: true)</parameter>
        </parameters>
    </tool>
    
    <tool>
        <name>GetSearchSummaryArgs</name>
        <description>Get information about available databases and search capabilities</description>
        <parameters>
            <parameter name="reasoning" type="string" required="true">Why this information is needed</parameter>
        </parameters>
    </tool>
</available_tools>

<search_tips>
    - Use simple, relevant keywords for broad searches
    - Common databases: WB_WDI (World Development Indicators), WB_HNP (Health Nutrition Population)
    - You can filter by database_id, topic, or other metadata fields
    - Results include search scores - higher scores indicate better matches
</search_tips>

<user_request>
    {{user_request}}
</user_request>
"""


def enhance_query(user_query: str, client: openai.OpenAI) -> str:
    """
    Layer 1: Enhance user query for better API search results using proven scoring patterns.

    Based on reverse engineering of the Data360 API scoring system:
    - Punctuation hurts scores (remove it)
    - More matching tokens = higher scores (2-3 optimal)
    - "total" keyword is powerful for aggregate indicators
    - Specific terms score higher (age ranges, domain terms)
    - Lowercase normalization happens anyway
    - Token repetition in titles boosts match scores

    Args:
        user_query: The original user query
        client: OpenAI client

    Returns:
        Enhanced query string optimized for API scoring
    """
    console.log("[blue]Layer 1:[/blue] Enhancing query with API scoring patterns...")

    enhancement_prompt = f"""Enhance this World Bank data search query for better API results using proven search optimization patterns.

User Query: "{user_query}"

Enhancement Rules (based on API scoring patterns):

1. REMOVE ALL PUNCTUATION (punctuation hurts scores):
   - "Population, total" → "population total"
   - "GDP (current US$)" → "GDP current US dollars"
   - Remove: commas, periods, parentheses, hyphens (except in age ranges like "0-14")

2. CONVERT ABBREVIATIONS to full text (increases token matching):
   - GDP → Gross Domestic Product
   - GNI → Gross National Income
   - HDI → Human Development Index
   - FDI → Foreign Direct Investment
   - CO2 → Carbon Dioxide
   - GHG → Greenhouse Gas
   - PPP → Purchasing Power Parity
   - etc.

3. ADD "TOTAL" keyword when appropriate (powerful scoring keyword):
   - "population" → "population total"
   - "employment" → "employment total"
   - "emissions" → "emissions total"
   - UNLESS user asks for: male, female, age groups, urban, rural, etc.

4. KEEP SPECIFIC TERMS (rare terms score higher):
   - Age ranges: "0-14", "65 and above"
   - Gender: "female", "male"
   - Domain terms: "labor force", "participation rate"
   - Geographic: "world", "urban", "rural"

5. LOWERCASE everything (API normalizes case anyway):
   - Use all lowercase for consistency

6. REMOVE FILLER WORDS (improve token efficiency):
   - Remove: "data", "statistics", "information", "about", "of the", "for the"
   - Keep: substantive keywords only

7. OPTIMAL TOKEN COUNT (2-3 content tokens work best):
   - Too few (1 token): scores ~35-45
   - Good (2-3 tokens): scores ~60-105
   - Too many: dilutes relevance

8. WORD ORDER FLEXIBILITY (bag-of-words approach):
   - "population total" = "total population" (both work)
   - Prioritize most important term first

Enhancement Examples:
- "GDP 2024" → "gross domestic product total"
- "population world" → "population total"
- "female employment rate" → "labor force female participation rate"
- "CO2 emissions per capita" → "carbon dioxide emissions total per capita"
- "life expectancy at birth" → "life expectancy total"
- "population ages 65+" → "population ages 65 above"
- "literacy rate, youth" → "literacy rate youth ages 15 24"

Return ONLY the enhanced query in lowercase, no punctuation, no explanation.

Enhanced Query:"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": enhancement_prompt}
            ],
            temperature=0.1,
            max_tokens=80
        )

        enhanced_query = response.choices[0].message.content.strip().strip('"').strip("'")
        console.log(f"[green]✓ Enhanced:[/green] '{user_query}' → '{enhanced_query}'")
        
        # Display optimization info
        original_tokens = len(user_query.split())
        enhanced_tokens = len(enhanced_query.split())
        console.log(f"[dim]Token count: {original_tokens} → {enhanced_tokens}[/dim]")
        
        return enhanced_query

    except Exception as e:
        console.log(f"[yellow]⚠ Enhancement failed, using original query[/yellow]")
        return user_query


def review_and_select_best(user_query: str, search_results: Dict[str, Any], client: openai.OpenAI) -> Dict[str, Any]:
    """
    Layer 2: Review search results and select the best matching database.

    Uses AI to evaluate which result best matches user intent, considering:
    - Relevance to original query
    - Preference for "total" or aggregate indicators (unless user specified breakdown)
    - Search score
    - Avoiding overly specific breakdowns

    Args:
        user_query: Original user query
        search_results: Results from the API search
        client: OpenAI client

    Returns:
        Result with best_match selected and reasoning
    """
    console.log("[blue]Layer 2:[/blue] Reviewing results with AI selection...")

    if "error" in search_results or not search_results.get("value"):
        return search_results

    results = search_results.get("value", [])[:10]  # Review top 10

    # Format results for review
    results_list = []
    for i, item in enumerate(results, 1):
        series = item.get("series_description", {})
        results_list.append({
            "rank": i,
            "name": series.get("name", ""),
            "idno": series.get("idno", ""),
            "database_id": series.get("database_id", ""),
            "score": round(item.get("@search.score", 0), 2)
        })

    review_prompt = f"""Review these World Bank database search results and select the BEST match.

User Query: "{user_query}"

Search Results:
{json.dumps(results_list, indent=2)}

Selection Criteria (in priority order):
1. **Relevance to user query** - Does it answer what they're asking?
2. **Prefer aggregates** - Choose "total" or aggregate indicators over demographic breakdowns (unless user specified gender/age)
3. **Higher search scores** - The API's scoring is generally reliable
4. **Avoid over-specificity** - Don't pick age/gender breakdowns unless explicitly requested
5. **Common databases** - WB_WDI is usually most comprehensive

Return ONLY valid JSON:
{{
  "best_rank": <number>,
  "reasoning": "<brief explanation why this is best match, max 50 words>"
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": review_prompt}
            ],
            temperature=0.2,
            max_tokens=150,
            response_format={"type": "json_object"}
        )

        selection = json.loads(response.choices[0].message.content)
        best_rank = selection.get("best_rank", 1)
        reasoning = selection.get("reasoning", "")

        # Get the selected result
        if 1 <= best_rank <= len(results_list):
            best_match = results_list[best_rank - 1]
            console.log(f"[green]✓ Selected:[/green] Rank {best_rank} - {best_match['name']}")
            console.log(f"[cyan]Reasoning:[/cyan] {reasoning}")

            # Add selection info to results
            search_results["best_match"] = best_match
            search_results["selection_reasoning"] = reasoning
        else:
            console.log(f"[yellow]⚠ Invalid rank {best_rank}, using top result[/yellow]")
            search_results["best_match"] = results_list[0]
            search_results["selection_reasoning"] = "Defaulted to highest scoring result"

        return search_results

    except Exception as e:
        console.log(f"[yellow]⚠ Review failed: {str(e)}[/yellow]")
        # Fallback to top result
        search_results["best_match"] = results_list[0]
        search_results["selection_reasoning"] = "Auto-selected highest scoring result"
        return search_results


def simple_search(reasoning: str, search_query: str, top: int = 10) -> Dict[str, Any]:
    """Perform a simple keyword search of Data360.

    Args:
        reasoning: Explanation of why this search is being performed
        search_query: The search term or phrase
        top: Number of results to return (1-100)

    Returns:
        Dictionary containing search results
    """
    console.log(f"[blue]Simple Search Tool[/blue] - Reasoning: {reasoning}")
    console.log(f"[cyan]Searching for:[/cyan] '{search_query}' (top {top} results)")

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
        console.log(
            f"[green]✓ Found {data.get('@odata.count', 0)} total results[/green]"
        )
        return data

    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {str(e)}"
        console.log(f"[red]✗ {error_msg}[/red]")
        return {"error": error_msg, "status_code": getattr(e.response, "status_code", None)}


def advanced_search(
    reasoning: str,
    search_query: str,
    select: str = "series_description/idno, series_description/name, series_description/database_id",
    filter_query: Optional[str] = None,
    top: int = 10,
    count: bool = True,
) -> Dict[str, Any]:
    """Perform an advanced search with filtering and custom field selection.

    Args:
        reasoning: Explanation for this search
        search_query: The search term or phrase
        select: Comma-separated list of fields to return
        filter_query: OData filter expression
        top: Number of results (1-100)
        count: Whether to include total count

    Returns:
        Dictionary containing search results
    """
    console.log(f"[blue]Advanced Search Tool[/blue] - Reasoning: {reasoning}")
    console.log(f"[cyan]Query:[/cyan] '{search_query}'")
    if filter_query:
        console.log(f"[cyan]Filter:[/cyan] {filter_query}")

    payload = {
        "count": count,
        "select": select,
        "search": search_query,
        "top": top,
    }

    if filter_query:
        payload["filter"] = filter_query

    try:
        response = requests.post(
            SEARCH_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        console.log(
            f"[green]✓ Found {data.get('@odata.count', 0)} total results[/green]"
        )
        return data

    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {str(e)}"
        console.log(f"[red]✗ {error_msg}[/red]")
        return {"error": error_msg, "status_code": getattr(e.response, "status_code", None)}


def get_search_summary(reasoning: str) -> Dict[str, Any]:
    """Get information about available databases and search capabilities.

    Args:
        reasoning: Why this information is needed

    Returns:
        Dictionary containing information about the API
    """
    console.log(f"[blue]Search Summary Tool[/blue] - Reasoning: {reasoning}")

    summary = {
        "api_endpoint": SEARCH_ENDPOINT,
        "common_databases": {
            "WB_WDI": "World Development Indicators - Key development data",
            "WB_HNP": "Health Nutrition and Population Statistics",
            "WB_GDF": "Global Development Finance",
            "WB_IDS": "International Debt Statistics",
        },
        "search_capabilities": [
            "Keyword search across all metadata fields",
            "Filter by database_id, topic, region, or other fields",
            "Select specific fields to return",
            "Paginate through results",
            "Get total result counts",
        ],
        "example_filters": [
            "database_id eq 'WB_WDI'",
            "database_id eq 'WB_HNP' and topic eq 'Health'",
        ],
        "tips": [
            "Use specific keywords for better results",
            "Start broad, then narrow with filters",
            "Check the idno field for unique indicator codes",
        ],
    }

    console.log("[green]✓ Retrieved API information[/green]")
    return summary


def format_results_table(results: Dict[str, Any], highlight_best: bool = True) -> None:
    """Display search results in a formatted table.

    Args:
        results: Dictionary containing search results from API
        highlight_best: Whether to highlight the best match selection
    """
    if "error" in results:
        console.print(f"[red]Error: {results['error']}[/red]")
        return

    total_count = results.get("@odata.count", 0)
    values = results.get("value", [])

    if not values:
        console.print("[yellow]No results found[/yellow]")
        return

    # Check if there's a best match selection
    best_match = results.get("best_match")
    best_idno = best_match.get("idno") if best_match else None

    # Create table
    table = Table(title=f"Search Results (showing {len(values)} of {total_count} total)")
    table.add_column("Rank", style="dim", no_wrap=True, width=5)
    table.add_column("Score", style="cyan", no_wrap=True, width=8)
    table.add_column("ID", style="green", width=25)
    table.add_column("Name", style="yellow")
    table.add_column("Database", style="magenta", width=12)

    for i, item in enumerate(values, 1):
        score = item.get("@search.score", "N/A")
        series = item.get("series_description", {})
        idno = series.get("idno", "N/A")
        name = series.get("name", "N/A")
        db = series.get("database_id", "N/A")
        
        # Highlight best match
        if highlight_best and best_idno and idno == best_idno:
            rank_style = "bold green"
            score_str = f"[bold green]{score}[/bold green] ⭐"
        else:
            rank_style = "dim"
            score_str = str(score)
        
        table.add_row(
            f"[{rank_style}]{i}[/{rank_style}]",
            score_str,
            idno,
            name,
            db,
        )

    console.print(table)
    
    # Show best match selection reasoning
    if best_match and results.get("selection_reasoning"):
        console.print(f"\n[bold green]⭐ Best Match:[/bold green] {best_match['name']}")
        console.print(f"[cyan]Reasoning:[/cyan] {results['selection_reasoning']}")


def main():
    """Main entry point for the World Bank Data360 Agent with enhanced two-layer reasoning."""
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="World Bank Data360 API Agent - Enhanced with API scoring pattern optimization"
    )
    parser.add_argument(
        "-p",
        "--prompt",
        required=True,
        help="Your data search request (e.g., 'Find population data for African countries')",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model to use (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "-c",
        "--compute",
        type=int,
        default=10,
        help="Maximum number of agent iterations (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted table",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of top results to return (default: 15, max: 100)",
    )
    parser.add_argument(
        "--no-enhance",
        action="store_true",
        help="Disable query enhancement (use original agent loop)",
    )
    args = parser.parse_args()

    # Configure OpenAI API
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print("[red]Error: OPENAI_API_KEY environment variable not set[/red]")
        console.print("Get your API key from https://platform.openai.com/api-keys")
        console.print("Then set it: export OPENAI_API_KEY='your-key-here'")
        sys.exit(1)

    client = openai.OpenAI(api_key=api_key)

    # ENHANCED TWO-LAYER SEARCH (default)
    if not args.no_enhance:
        console.print(
            Panel(
                f"[bold cyan]Enhanced Two-Layer Search[/bold cyan]\n"
                f"[dim]Using API scoring pattern optimization[/dim]\n\n"
                f"{args.prompt}",
                title="🔍 Data360 Search Agent"
            )
        )

        try:
            # Layer 1: Enhance query using scoring patterns
            enhanced_query = enhance_query(args.prompt, client)

            # Perform search with enhanced query
            console.log(f"[blue]Searching API with optimized query...[/blue]")
            search_results = simple_search(
                reasoning="Optimized query search using scoring patterns",
                search_query=enhanced_query,
                top=args.top
            )

            # Layer 2: Review and select best match using AI
            final_results = review_and_select_best(args.prompt, search_results, client)

            # Layer 3: Extract parameters from query
            console.log("[blue]Layer 3:[/blue] Extracting parameters from user query...")
            extracted_params = extract_parameters(args.prompt)
            if extracted_params:
                final_results["extracted_params"] = extracted_params
                param_summary = get_extracted_params_summary(extracted_params)
                console.log(f"[green]✓ Extracted filters:[/green] {param_summary}")
                console.log(f"[cyan]Parameter details:[/cyan] {extracted_params}")

                # Highlight country filter if present
                if "REF_AREA" in extracted_params:
                    console.log(f"[bold green]→ Country filter will be applied: {extracted_params['REF_AREA']}[/bold green]")
            else:
                console.log("[yellow]⚠ No filters extracted - will retrieve ALL countries[/yellow]")

            # Display final results
            console.rule("[bold green]Final Results[/bold green]")
            if args.json:
                console.print(JSON(json.dumps(final_results, indent=2)))
            else:
                format_results_table(final_results, highlight_best=True)

            sys.exit(0)

        except Exception as e:
            console.print(f"[red]Error in enhanced search: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # ORIGINAL AGENT LOOP (fallback when --no-enhance is used)
    console.print(
        Panel(f"[bold cyan]World Bank Data360 Search[/bold cyan]\n{args.prompt}")
    )

    # Create initial prompt
    completed_prompt = (AGENT_PROMPT
                       .replace("{{user_request}}", args.prompt)
                       .replace("{{recommended_top}}", str(args.top)))
    messages = [{"role": "user", "content": completed_prompt}]

    compute_iterations = 0
    final_results = None

    # Main agent loop
    while compute_iterations < args.compute:
        console.rule(f"[yellow]Agent Iteration {compute_iterations + 1}/{args.compute}[/yellow]")
        compute_iterations += 1

        try:
            # Call OpenAI API
            response = client.chat.completions.create(
                model=args.model, messages=messages, tools=tools
            )

            if not response.choices:
                console.print("[yellow]No response from API[/yellow]")
                break

            message = response.choices[0].message

            # Check if agent wants to call a tool
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                func_call = tool_call.function
                func_name = func_call.name
                func_args_str = func_call.arguments

                # Add assistant message to conversation
                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": func_call,
                            }
                        ],
                    }
                )

                console.print(f"[blue]Tool Call:[/blue] {func_name}")

                try:
                    # Execute the appropriate tool
                    if func_name == "SimpleSearchArgs":
                        args_parsed = SimpleSearchArgs.model_validate_json(func_args_str)
                        result = simple_search(
                            reasoning=args_parsed.reasoning,
                            search_query=args_parsed.search_query,
                            top=args_parsed.top,
                        )
                        final_results = result

                    elif func_name == "AdvancedSearchArgs":
                        args_parsed = AdvancedSearchArgs.model_validate_json(func_args_str)
                        result = advanced_search(
                            reasoning=args_parsed.reasoning,
                            search_query=args_parsed.search_query,
                            select=args_parsed.select,
                            filter_query=args_parsed.filter_query,
                            top=args_parsed.top,
                            count=args_parsed.count,
                        )
                        final_results = result

                    elif func_name == "GetSearchSummaryArgs":
                        args_parsed = GetSearchSummaryArgs.model_validate_json(
                            func_args_str
                        )
                        result = get_search_summary(reasoning=args_parsed.reasoning)

                    else:
                        raise ValueError(f"Unknown tool: {func_name}")

                    # Add tool result to conversation
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result),
                        }
                    )

                except Exception as e:
                    error_msg = f"Tool execution failed: {str(e)}"
                    console.print(f"[red]{error_msg}[/red]")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": error_msg}),
                        }
                    )

            # Check if agent provided a text response (done with tool calls)
            elif message.content:
                console.print("\n[bold green]Agent Response:[/bold green]")
                console.print(message.content)
                break

            else:
                console.print("[yellow]No action taken by agent[/yellow]")
                break

        except Exception as e:
            console.print(f"[red]Error in agent loop: {str(e)}[/red]")
            sys.exit(1)

    # Display final results
    if final_results:
        # Extract parameters from query
        extracted_params = extract_parameters(args.prompt)
        if extracted_params:
            final_results["extracted_params"] = extracted_params
            param_summary = get_extracted_params_summary(extracted_params)
            console.log(f"[cyan]Extracted filters:[/cyan] {param_summary}")
            console.log(f"[dim]Parameters:[/dim] {extracted_params}")

        console.rule("[bold green]Final Results[/bold green]")
        if args.json:
            console.print(JSON(json.dumps(final_results, indent=2)))
        else:
            format_results_table(final_results, highlight_best=False)

    if compute_iterations >= args.compute:
        console.print(
            f"[yellow]⚠ Reached maximum iterations ({args.compute})[/yellow]"
        )


if __name__ == "__main__":
    main()