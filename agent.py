import os
import re
import logging  # Added for youtube scraper logging visibility
from typing import Any, Dict, TypedDict, Union, Optional

from baml_client import b
from baml_client.types import ContentType, Summary, ExtractorTool
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from rich.console import Console
from tools.search import run_tavily_tool
from tools.pdf_handler import get_pdf_text
from tools.twitter_api_tool import fetch_tweet_thread
from tools.linkedin_agentql_scraper import (
    scrape_linkedin_post as scrape_linkedin_post_agentql,
)
from tools.youtube_agentql_scraper import scrape_youtube as scrape_youtube_agentql

load_dotenv()

console = Console()

# Configure logging slightly for better visibility from tools
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce noise from http libraries
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

# --- LangGraph Agent State ---


class AgentState(TypedDict):
    original_message: str
    url: str
    content_type: ContentType  # 'web' or 'pdf' or others?
    content: str
    summary: str
    error: Optional[str]
    route_decision: Optional[str]  # To store the routing decision string
    needs_web_fallback: bool  # Flag for YouTube fallback


# --- Define Graph Nodes ---


def init_state(state: AgentState) -> Dict[str, Any]:
    """Extracts the URL from the original message."""
    console.print("---INIT STATE---", style="yellow bold")
    message = state["original_message"]
    # Basic URL extraction (consider a more robust regex)
    url = next((word for word in message.split() if word.startswith("http")), None)
    error = None if url else "No URL found in the message."

    if error:
        console.print(f"Initialization error: {error}", style="red")

    return {
        "original_message": message,
        "url": url if url else "",  # Ensure url is always a string
        "content_type": ContentType.Webpage,  # Default, gets updated later
        "content": "",
        "summary": "",
        "error": error,
        "route_decision": None,
        "needs_web_fallback": False,  # Initialize flag
    }


async def llm_router(state: AgentState) -> Dict[str, Any]:
    """Determines the content extraction route using the BAML LLM Router."""
    console.print("---LLM ROUTER (BAML)--- ", style="yellow bold")

    # If init failed, pass the error along
    if state.get("error"):
        console.print(
            f"Skipping LLM Router due to init error: {state['error']}", style="red"
        )
        return {"error": state["error"], "route_decision": "__error__"}

    message = state["original_message"]
    decision = "__error__"  # Default to error
    routing_error = None

    try:
        console.print(
            f"Calling BAML RouteRequest for: '{message[:50]}...'", style="cyan"
        )
        # Call the BAML function (synchronously, as it's not declared async in BAML)
        route_result: ExtractorTool = b.RouteRequest(original_message=message)

        console.print(f"LLM Router returned: {route_result}", style="green")

        # Map the enum result to string for routing
        if route_result == ExtractorTool.WebpageExtractor:
            decision = "web_extractor"
        elif route_result == ExtractorTool.PDFExtractor:
            decision = "pdf_extractor"
        elif route_result == ExtractorTool.TwitterExtractor:
            decision = "twitter_extractor"
        elif route_result == ExtractorTool.LinkedInExtractor:
            decision = "linkedin_extractor"
        elif route_result == ExtractorTool.YoutubeExtractor:
            decision = "youtube_extractor"  # Added Youtube route
        elif route_result == ExtractorTool.Unsupported:
            decision = "__unsupported__"
            routing_error = "Unsupported URL type or no URL found by LLM Router."
            console.print(routing_error, style="yellow")
        else:
            # Should not happen if enum is handled correctly
            decision = "__error__"
            routing_error = f"LLM Router returned an unexpected value: {route_result}"
            console.print(routing_error, style="red")

    except Exception as e:
        console.print(f"Error calling BAML RouteRequest: {e}", style="red bold")
        routing_error = f"LLM Router failed: {e}"
        decision = "__error__"

    # Update the state dictionary
    return {
        "route_decision": decision,
        "error": routing_error,  # Overwrite previous error state if routing fails
    }


def get_web_content(state: AgentState) -> Dict[str, Any]:
    """Fetches content from a standard webpage URL using Tavily extract."""
    console.print("---GET WEB CONTENT (Tavily Extract)--- ", style="yellow bold")
    url = state["url"]
    error_message = None
    content_source = ""
    content_type = ContentType.Webpage

    # Reset error from previous steps if any
    state["error"] = None
    # Reset fallback flag if we reached here directly or as fallback
    state["needs_web_fallback"] = False

    try:
        # Use Tavily extract for non-Twitter URLs
        console.print(f"Using Tavily extract for: {url}", style="cyan")
        extract_tool_results = run_tavily_tool(mode="extract", urls=[url])
        results_list = extract_tool_results.get("results", [])
        failed_results = extract_tool_results.get("failed_results", [])

        if results_list:
            for res in results_list:
                # Try to get 'raw_content' first, fallback to 'content'
                raw_content = res.get("raw_content")
                if not raw_content:
                    raw_content = res.get(
                        "content", ""
                    )  # Fallback if raw_content is missing

                # Ensure raw_content is a string (Tavily may return dict for some URLs)
                if isinstance(raw_content, dict):
                    raw_content = raw_content.get("text", str(raw_content))
                if raw_content:
                    content_source += f"URL: {res.get('url', 'N/A')}\n"
                    content_source += f"Raw Content: {raw_content}\n\n"
                # Optional: Include images if needed later
                # content_source += f"Images: {res.get('images', [])}\n"

        if failed_results:
            failed_urls = [r.get("url", str(r)) if isinstance(r, dict) else str(r) for r in failed_results]
            error_message = (
                f"Tavily failed to extract content from: {', '.join(failed_urls)}"
            )
            console.print(error_message, style="red")
            # If extraction failed entirely and we have no content, set content_source empty
            if not content_source:
                content_source = ""

        # If Tavily failed, try Playwright fallback (JS-rendered pages like Grok)
        if not content_source:
            console.print("Tavily returned no content — trying Playwright fallback...", style="yellow")
            try:
                from tools.playwright_fallback import extract_page_text
                pw_text = extract_page_text(url)
                if pw_text:
                    content_source = f"URL: {url}\nRaw Content: {pw_text}\n"
                    error_message = None  # Clear error since fallback succeeded
                else:
                    error_message = error_message or f"Both Tavily and Playwright failed to extract content from {url}"
            except Exception as pw_err:
                console.print(f"Playwright fallback error: {pw_err}", style="red")
                error_message = error_message or f"Tavily and Playwright both failed for {url}"

    except Exception as e:
        console.print(f"Error getting content from URL {url}: {e}", style="red bold")
        error_message = f"Error: An unexpected error occurred while getting content from the URL. {e}"
        content_source = ""  # Ensure content is empty on error

    return {
        # **state, # Don't spread the entire state, just update relevant fields
        "content_type": content_type,
        "content": content_source.strip(),  # Strip leading/trailing whitespace
        "error": error_message,
        "needs_web_fallback": False,  # Explicitly set to false after web extraction
    }


def get_twitter_content(state: AgentState) -> Dict[str, Any]:
    """Fetches content from a Twitter/X URL using twitter_api_tool.

    X Articles (long-form posts) are detected and extracted via Playwright
    instead of the Twitter API, since the API returns minimal data for articles.
    """
    console.print("---GET TWITTER/X CONTENT (twitterapi.io)--- ", style="yellow bold")
    url = state["url"]
    error_message = None
    content_result = ""
    content_type = ContentType.Webpage

    # Reset error from previous steps if any
    state["error"] = None
    state["needs_web_fallback"] = False  # Reset flag

    # Detect X Articles — they have /article/ in path or are long-form content
    # that the Twitter API can't handle well
    is_article = "/article/" in url.lower() or "/articles/" in url.lower()

    if is_article:
        console.print("Detected X Article — using Playwright for full content", style="cyan")
        try:
            from tools.playwright_fallback import extract_page_text
            pw_text = extract_page_text(url, timeout_ms=30000)
            if pw_text and len(pw_text) > 100:
                content_result = pw_text
                console.print(f"Playwright extracted {len(pw_text)} chars from X Article", style="green")
            else:
                error_message = "Could not extract X Article content."
        except Exception as e:
            error_message = f"Error extracting X Article: {e}"
            console.print(error_message, style="red")

        return {
            "content_type": content_type,
            "content": content_result.strip(),
            "error": error_message,
            "needs_web_fallback": False,
        }

    try:
        console.print(f"Fetching tweet thread for URL: {url}", style="cyan")
        # Use the new tool
        content_result = fetch_tweet_thread(url)

        # Check if the tool returned an error message
        if isinstance(content_result, str) and content_result.startswith("Error:"):
            error_message = content_result
            console.print(error_message, style="red bold")
            content_result = ""  # Ensure content is empty if tool errored
        elif not content_result:  # Handle empty success case
            error_message = "Twitter tool returned no content."
            console.print(error_message, style="yellow")
            content_result = ""
        else:
            console.print(
                f"Successfully fetched Twitter content for: {url}", style="green"
            )
            # Ensure content_result is a string
            if not isinstance(content_result, str):
                content_result = str(content_result)

            # If tweet is mostly a link with little text, follow the embedded URL
            import re as _re
            import requests as _requests
            embedded_urls = _re.findall(r'https?://t\.co/\S+|https?://(?!x\.com|twitter\.com)\S+', content_result)
            tweet_text_only = _re.sub(r'https?://\S+', '', content_result).strip()
            if embedded_urls and len(tweet_text_only) < 100:
                # Resolve t.co redirects to get the actual URL
                target_url = embedded_urls[0]
                if "t.co/" in target_url:
                    try:
                        resp = _requests.head(target_url, allow_redirects=True, timeout=5)
                        target_url = resp.url
                        console.print(f"Resolved t.co → {target_url}", style="cyan")
                    except Exception:
                        pass

                console.print(f"Tweet is mostly a link — extracting: {target_url}", style="cyan")
                extracted = False
                try:
                    link_content = run_tavily_tool(mode="extract", urls=[target_url])
                    results_list = link_content.get("results", []) if isinstance(link_content, dict) else []
                    if results_list:
                        raw = results_list[0].get("raw_content") or results_list[0].get("content", "")
                        if isinstance(raw, dict):
                            raw = raw.get("text", str(raw))
                        if raw and len(raw) > 100:
                            content_result = f"Tweet by {content_result}\n\n--- Linked Content ---\n{raw[:10000]}"
                            console.print(f"Tavily extracted {len(raw)} chars from linked URL", style="green")
                            extracted = True
                except Exception as link_err:
                    console.print(f"Tavily failed for linked URL: {link_err}", style="yellow")

                # Fallback to Playwright if Tavily didn't get content
                if not extracted:
                    try:
                        from tools.playwright_fallback import extract_page_text
                        pw_text = extract_page_text(target_url)
                        if pw_text and len(pw_text) > 100:
                            content_result = f"Tweet by {content_result}\n\n--- Linked Content ---\n{pw_text}"
                            console.print(f"Playwright extracted {len(pw_text)} chars from linked URL", style="green")
                    except Exception as pw_err:
                        console.print(f"Playwright fallback failed: {pw_err}", style="yellow")

    except Exception as e:
        console.print(
            f"Unexpected error calling fetch_tweet_thread for {url}: {e}",
            style="red bold",
        )
        error_message = (
            f"Error: An unexpected error occurred while calling the Twitter tool. {e}"
        )
        content_result = ""

    # Last resort: if content is still too thin, the URL might be an X Article
    # or rich thread that the API didn't capture. Try Playwright on original URL.
    clean_text = _re.sub(r'https?://\S+', '', content_result).strip() if content_result else ""
    if len(clean_text) < 200 and not error_message:
        console.print("Tweet content too thin — trying Playwright on original URL as article fallback", style="cyan")
        try:
            from tools.playwright_fallback import extract_page_text
            pw_text = extract_page_text(url, timeout_ms=30000)
            if pw_text and len(pw_text) > 200:
                content_result = pw_text
                console.print(f"Playwright extracted {len(pw_text)} chars from X URL", style="green")
        except Exception as pw_err:
            console.print(f"Playwright article fallback failed: {pw_err}", style="yellow")

    return {
        "content_type": content_type,
        "content": content_result.strip(),
        "error": error_message,
        "needs_web_fallback": False,
    }


def get_linkedin_content(state: AgentState) -> Dict[str, Any]:
    """Fetches content from a LinkedIn post URL using linkedin_scraper_tool."""
    console.print(
        "---GET LINKEDIN CONTENT (linkedin_scraper_tool)--- ", style="yellow bold"
    )
    url = state["url"]
    error_message = None
    content_result = ""
    content_type = (
        ContentType.Webpage
    )  # LinkedIn posts are treated as webpages for summarization

    # Reset error from previous steps if any
    state["error"] = None
    state["needs_web_fallback"] = False  # Reset flag

    try:
        console.print(f"Fetching LinkedIn post content for URL: {url}", style="cyan")
        # Use the LinkedIn tool (AgentQL version)
        result = scrape_linkedin_post_agentql(
            url, headless=True
        )  # Call with headless=True

        # AgentQL scraper returns a dict: {"author": "...", "content": "..."}
        if isinstance(result, dict) and result.get("content"):
            content_result = result["content"]
            # author = result.get("author") # Author is available if needed later
            console.print(
                f"Successfully fetched LinkedIn content (AgentQL) for: {url}",
                style="green",
            )
            if not isinstance(content_result, str):
                content_result = str(content_result)
        elif (
            isinstance(result, dict) and "error" in result
        ):  # Check for an error key if scraper returns errors that way
            error_message = (
                f"LinkedIn AgentQL scraper returned an error: {result['error']}"
            )
            console.print(error_message, style="red bold")
            content_result = ""
        else:
            error_message = f"LinkedIn AgentQL scraper returned unexpected result or no content: {result}"
            console.print(error_message, style="yellow")
            content_result = ""

    except Exception as e:
        console.print(
            f"Unexpected error calling scrape_linkedin_post for {url}: {e}",
            style="red bold",
        )
        error_message = (
            f"Error: An unexpected error occurred while calling the LinkedIn tool. {e}"
        )
        content_result = ""

    return {
        # **state,
        "content_type": content_type,
        "content": content_result.strip(),
        "error": error_message,
        "needs_web_fallback": False,
    }


def get_youtube_content(state: AgentState) -> Dict[str, Any]:
    """Fetches content (description/transcript) using youtube_scraper with fallbacks."""
    console.print(
        "---GET YOUTUBE CONTENT (yt-dlp + Fallbacks)--- ", style="yellow bold"
    )
    url = state["url"]
    error_message = None
    content_result = ""
    # For YouTube, let's treat the content type as Webpage for the summarizer initially
    content_type = ContentType.Webpage

    # Reset error and fallback flag from previous steps if any
    state["error"] = None
    # No longer using needs_web_fallback with AgentQL direct approach
    # state["needs_web_fallback"] = False

    try:
        console.print(f"Fetching YouTube info for URL (AgentQL): {url}", style="cyan")
        # Use the YouTube AgentQL tool
        result = scrape_youtube_agentql(url, headless=True)  # Call with headless=True

        # AgentQL scraper returns: {"title": "...", "description": "..."}
        if isinstance(result, dict) and (
            result.get("title") or result.get("description")
        ):
            title = result.get("title", "")
            description = result.get("description", "")
            content_result = f"Title: {title}\n\nDescription:\n{description}".strip()
            console.print(
                f"Successfully fetched YouTube content (AgentQL) for: {url}",
                style="green",
            )
            error_message = None
        elif (
            isinstance(result, dict) and "error" in result
        ):  # If scraper returns dict with error
            error_message = (
                f"YouTube AgentQL scraper returned an error: {result['error']}"
            )
            console.print(error_message, style="red bold")
            content_result = ""
        else:
            error_message = f"YouTube AgentQL scraper returned unexpected result or no content: {result}"
            console.print(error_message, style="yellow")
            content_result = ""

    except Exception as e:
        console.print(
            f"Unexpected error calling scrape_youtube_agentql for {url}: {e}",
            style="red bold",
        )
        error_message = f"Error: An unexpected error occurred while calling the YouTube AgentQL tool. {e}"
        content_result = ""
        # needs_fallback = False # Not used anymore

    return {
        # **state,
        "content_type": content_type,
        "content": content_result.strip(),
        "error": error_message,  # Will be None if successful
        "needs_web_fallback": False,  # Explicitly set to false, not used for fallback anymore
    }


def handle_pdf_content(state: AgentState) -> Dict[str, Any]:
    """Downloads and extracts text from a PDF URL."""
    console.print("---HANDLE PDF CONTENT--- ", style="bold yellow")
    url = state["url"]
    error_message = None
    pdf_text = ""

    # Reset error from previous steps if any
    state["error"] = None
    state["needs_web_fallback"] = False  # Reset flag

    try:
        extracted_text = get_pdf_text(url)
        if isinstance(extracted_text, str) and extracted_text.startswith("Error:"):
            console.print(
                f"Error getting PDF content: {extracted_text}", style="red bold"
            )
            error_message = extracted_text
        elif not extracted_text:
            error_message = "PDF extraction returned no text."
            console.print(error_message, style="yellow")
        else:
            console.print(
                f"Successfully extracted text from PDF: {url}", style="magenta"
            )
            pdf_text = extracted_text
            # Ensure text is string
            if not isinstance(pdf_text, str):
                pdf_text = str(pdf_text)

    except Exception as e:
        console.print(f"Unexpected error handling PDF {url}: {e}", style="red bold")
        error_message = (
            f"Error: An unexpected error occurred while processing the PDF. {e}"
        )

    return {
        # **state,
        "content": pdf_text.strip(),
        "content_type": ContentType.PDF,
        "error": error_message,
        "needs_web_fallback": False,
    }


async def summarize_content(state: AgentState) -> Dict[str, Any]:
    """Summarizes the extracted content using BAML."""
    console.print("---SUMMARIZE CONTENT--- ", style="bold green")

    content_to_summarize = state.get("content")

    # If there was an error *before* summarization, don't proceed
    if state.get("error"):
        console.print(
            f"Skipping summarization due to previous error: {state['error']}",
            style="yellow",
        )
        return {"summary": "", "error": state["error"]}  # Keep existing error

    if not content_to_summarize or content_to_summarize.strip() == "":
        console.print("No content available to summarize.", style="yellow")
        # If we reached here due to an upstream error, preserve it
        # Otherwise, set an error indicating no content.
        final_error = state.get("error") or "No content found to summarize."
        return {
            "summary": "",
            "error": final_error,
        }

    url = state.get("url", "Unknown URL")
    summarization_error = None
    formatted_summary = ""

    try:
        console.print(
            f"--- Debug: Summarizing {len(content_to_summarize)} chars --- ",
            style="dim",
        )
        # Ensure content_type is valid, default to Webpage if missing/invalid
        content_type = state.get("content_type", ContentType.Webpage)
        if not isinstance(content_type, ContentType):
            content_type = ContentType.Webpage  # Default fallback

        # Call the BAML function (assuming it's synchronous based on definition)
        summary_result: Summary = b.SummarizeContent(
            content=content_to_summarize,
            content_type=content_type,
            context=state.get("original_message", ""),
        )
        console.print(f"Successfully generated summary.", style="bold green")
        title = getattr(summary_result, "title", "Summary")  # Default title
        key_points = getattr(summary_result, "key_points", [])
        concise_summary = getattr(
            summary_result,
            "concise_summary",
            "Summarization service returned an unexpected response format.",
        )

        # Ensure parts are strings
        title = str(title) if title else "Summary"
        key_points = [str(p).strip() for p in key_points if p]
        concise_summary = (
            str(concise_summary).strip() if concise_summary else "No summary generated."
        )

        formatted_summary = f"# {title}\n\n"
        if key_points:
            formatted_summary += "## Key Points:\n"
            for point in key_points:
                formatted_summary += f"- {point}\n"
            formatted_summary += "\n"  # Add space before summary
        formatted_summary += f"## Summary:\n{concise_summary}"
        formatted_summary = re.sub(r"\n\s*\n", "\n\n", formatted_summary).strip()

        # Clear any previous error if summarization succeeds
        summarization_error = None

    except Exception as e:
        console.print(f"Error during summarization for {url}: {e}", style="red bold")
        print(f"--- Debug: BAML summarization error: {e} ---")
        summarization_error = f"Summarization failed: {e}"
        formatted_summary = ""  # Ensure summary is empty on error

    # Return only summary and error, let graph manage state merge
    return {
        "summary": formatted_summary,
        "error": summarization_error,  # Overwrite previous errors only if summarization fails
    }


# --- Conditional Edges Logic ---


def route_based_on_llm(state: AgentState) -> str:
    """Routes to the appropriate extractor based on the LLM router decision."""
    console.print("---ROUTING (LLM Decision)--- ", style="yellow bold")
    decision = state.get("route_decision")
    error = state.get("error")  # Check for errors from init or router node

    if error:
        console.print(f"Routing to END due to error: {error}", style="red")
        return END

    if decision == "web_extractor":
        console.print(f"LLM Routed to: Web Extractor", style="magenta")
        return "web_extractor"
    elif decision == "pdf_extractor":
        console.print(f"LLM Routed to: PDF Extractor", style="magenta")
        return "pdf_extractor"
    elif decision == "twitter_extractor":
        console.print(f"LLM Routed to: Twitter Extractor", style="magenta")
        return "twitter_extractor"
    elif decision == "linkedin_extractor":
        console.print(f"LLM Routed to: LinkedIn Extractor", style="magenta")
        return "linkedin_extractor"
    elif decision == "youtube_extractor":
        console.print(f"LLM Routed to: YouTube Extractor", style="magenta")
        return "youtube_extractor"  # Added Youtube route
    elif decision == "__unsupported__":
        console.print("LLM Routed to: Unsupported -> END", style="yellow")
        # Error message should already be set by the router node
        return END
    else:  # Includes __error__ or unexpected values
        console.print(
            f"LLM Routing decision invalid or error ('{decision}'). Routing to END.",
            style="red",
        )
        # Ensure error state reflects this if not already set
        current_error = state.get("error")
        if not current_error:
            # Update state directly is tricky in conditional functions.
            # Ideally, the router node should set the error if decision is __error__.
            # For now, just log and route to end.
            console.print(
                f"Setting error state due to invalid routing: {decision}", style="red"
            )
            # state["error"] = f"Invalid routing decision: {decision}"
        return END


def should_summarize(state: AgentState) -> str:
    """Determines whether to proceed to summarization or end after extraction."""
    content = state.get("content")
    error = state.get("error")  # Check error from the *extractor* node
    has_content = content and isinstance(content, str) and content.strip() != ""
    # needs_fallback is no longer used for YouTube -> Webpage fallback
    # if needs_fallback:
    #     console.print(
    #         "Routing after Extraction: YouTube fallback failed, routing to Web Extractor.",
    #         style="yellow",
    #     )
    #     return "web_extractor"  # Route to web extractor as the last resort

    if error:
        console.print(
            f"Routing after Extraction: Error occurred ('{error}'), routing to END.",
            style="red",
        )
        return END
    elif has_content:
        console.print(
            "Routing after Extraction: Content extracted successfully, routing to Summarize.",
            style="green",
        )
        return "summarize_content"
    else:
        console.print(
            "Routing after Extraction: No content extracted and no specific error, routing to END.",
            style="yellow",
        )
        # Set an error if none exists from the extractor
        current_error = state.get("error")
        final_error = current_error or "Content extraction finished with no content."
        # state["error"] = final_error # Avoid direct state modification here
        console.print(f"Setting error state: {final_error}", style="yellow")
        # How to set error state correctly before END?
        # LangGraph merges the partial state returned by the node *after* the edge logic.
        # We might need an explicit error handling node.
        # For now, just route to END. The final state check should catch the lack of summary.
        return END


# --- Build the Graph ---


def build_graph():
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("init", init_state)
    workflow.add_node("llm_router", llm_router)  # New router node
    workflow.add_node("web_extractor", get_web_content)
    workflow.add_node("pdf_extractor", handle_pdf_content)
    workflow.add_node("twitter_extractor", get_twitter_content)
    workflow.add_node("linkedin_extractor", get_linkedin_content)
    workflow.add_node("youtube_extractor", get_youtube_content)  # Add new node
    workflow.add_node("summarize_content", summarize_content)

    # Define edges
    workflow.set_entry_point("init")

    # Edge from init to the LLM router
    workflow.add_edge("init", "llm_router")

    # Conditional routing based on LLM Router output
    workflow.add_conditional_edges(
        "llm_router",
        route_based_on_llm,
        {
            "web_extractor": "web_extractor",
            "pdf_extractor": "pdf_extractor",
            "twitter_extractor": "twitter_extractor",
            "linkedin_extractor": "linkedin_extractor",
            "youtube_extractor": "youtube_extractor",  # Add edge to new node
            END: END,  # Handles errors and unsupported cases from the router
        },
    )

    # Route from each extractor to the summarization check
    # Note: The should_summarize function now handles routing to web_extractor for YouTube fallback
    workflow.add_conditional_edges(
        "web_extractor",
        should_summarize,
        {
            "summarize_content": "summarize_content",
            END: END,
            # No web_extractor fallback from web_extractor itself
        },
    )
    workflow.add_conditional_edges(
        "pdf_extractor",
        should_summarize,
        {
            "summarize_content": "summarize_content",
            END: END,
            # No web_extractor fallback needed from pdf
        },
    )
    workflow.add_conditional_edges(
        "twitter_extractor",
        should_summarize,
        {
            "summarize_content": "summarize_content",
            END: END,
            # No web_extractor fallback needed from twitter
        },
    )
    workflow.add_conditional_edges(
        "linkedin_extractor",
        should_summarize,
        {
            "summarize_content": "summarize_content",
            END: END,
            # No web_extractor fallback needed from linkedin
        },
    )
    workflow.add_conditional_edges(
        "youtube_extractor",  # Edges from YouTube extractor
        should_summarize,  # Use the same logic function, now enhanced
        {
            "summarize_content": "summarize_content",
            END: END,
        },
    )

    # Summarizer always goes to end
    workflow.add_edge("summarize_content", END)

    return workflow.compile()


graph = build_graph()

# --- Main Agent Function ---


async def run_agent(message: str) -> Union[str, None]:
    """
    Runs the LangGraph agent workflow for URL summarization using an LLM router.

    Args:
        message: The original message potentially containing a URL.

    Returns:
        - str: Summary text on successful extraction and summarization.
        - str: An error message string if a significant error occurred.
        - None: Should ideally not be returned if error handling is robust.
    """
    inputs = {"original_message": message}
    final_state = None
    try:
        # Use graph.astream for async execution
        async for output in graph.astream(
            inputs, {"recursion_limit": 15}
        ):  # Increased recursion limit
            # output is a dictionary where keys are node names and values are states after the node ran
            # We are interested in the state *after* the last node executes
            node_name = list(output.keys())[0]
            final_state = output[node_name]  # Keep track of the latest state
            console.print(f"Output from node '{node_name}': Updated state", style="dim")
            # Optional: Print intermediate state details if needed for debugging
            # console.print(f"  State keys: {list(final_state.keys())}", style="dim")

        if final_state:
            # Debug: Print the final state (simplified)
            console.print("---FINAL STATE--- ", style="bold magenta")
            # Sort keys for consistent output order
            state_keys = sorted(final_state.keys())
            for key in state_keys:
                value = final_state[key]
                if key == "content" and isinstance(value, str) and len(value) > 200:
                    console.print(
                        f"  {key}: <string> ({len(value)} chars)", style="magenta"
                    )
                elif isinstance(value, str) and len(value) > 100:
                    console.print(
                        f"  {key}: <string> ({len(value)} chars)", style="magenta"
                    )
                else:
                    console.print(f"  {key}: {value}", style="magenta")

            # Determine final result based on summary and error fields
            summary_text = final_state.get("summary")
            final_error = final_state.get("error")

            # 1. Successful Summary (even if there were intermediate, recoverable errors)
            if summary_text and isinstance(summary_text, str) and summary_text.strip():
                console.print("---AGENT FINISHED: Summary--- ", style="bold green")
                # If an error occurred *before* summarization, but summarization *still* happened
                # (e.g. fallback content used), we might want to mention the error.
                # For now, prioritize showing the summary if available.
                # if final_error:
                #     console.print(f"(Note: An earlier error occurred: {final_error})", style="yellow")
                return summary_text

            # 2. Error occurred (could be init, routing, extraction, or summarization error)
            elif final_error:
                console.print(
                    f"---AGENT FINISHED: Error ('{final_error}')--- ", style="bold red"
                )
                # Ensure the error message is prefixed consistently
                if isinstance(final_error, str) and final_error.lower().startswith(
                    "error:"
                ):
                    return final_error
                else:
                    return "Error: " + str(final_error)  # Ensure it's a string

            # 3. No Summary and No Error (Should ideally not happen with should_summarize logic,
            #    but could occur if summarizer returns empty without error)
            else:
                console.print(
                    "---AGENT FINISHED: No Summary/No Error--- ", style="bold yellow"
                )
                # Provide a more specific fallback message
                if not final_state.get("content"):
                    # Check if it was an unsupported URL type initially
                    if final_state.get("route_decision") == "__unsupported__":
                        return "Error: The provided link type is not supported or no URL was found."
                    else:
                        return "Error: Agent finished without extracting content."
                else:
                    return "Error: Agent finished. Content was extracted, but no summary was generated and no specific error was reported."

        else:
            console.print("---AGENT FAILED: No Final State--- ", style="bold red")
            return "Error: Agent workflow did not produce a final state."

    except Exception as e:
        console.print("---AGENT FAILED: Runtime Exception--- ", style="bold red")
        console.print_exception(show_locals=False)
        # Ensure the exception is converted to a string for the return value
        return "Error: An unexpected error occurred in the agent: " + str(e)


# Example usage (for testing)
if __name__ == "__main__":
    import asyncio

    # --- Test Cases ---
    # Twitter/X URL
    test_url_msg_twitter = (
        "Summarize this tweet: https://x.com/natolambert/status/1917928418068541520"
    )
    # Standard Web URL
    test_url_msg_web = (
        "Can you summarize this? https://lilianweng.github.io/posts/2023-06-23-agent/"
    )
    # PDF URL
    test_url_msg_pdf = "Summarize: https://arxiv.org/pdf/2305.15334.pdf"
    # URL that might fail primary extraction (Tavily might fail, but router should still pick web)
    test_url_msg_fail = (
        "What about this? https://httpbin.org/delay/5"  # Example, Tavily might timeout
    )
    # LinkedIn URL
    test_url_msg_linkedin = "Summarize this post: https://www.linkedin.com/posts/omarsar_llms-for-engineering-activity-7324064951734603776-Ravc?utm_source=share&utm_medium=member_desktop&rcm=ACoAABDFOm0BmXlu4cLYtJePo0mLzdFoB5itUNU"
    # Message without a URL (Router should pick Unsupported)
    test_url_msg_nourl = "Hello, how are you?"
    # Unsupported URL Type (Router should pick Unsupported)
    test_url_msg_unsupported = "Check this out: ftp://files.example.com/data.zip"
    # YouTube URL (Router should pick Youtube)
    test_url_msg_youtube = "Summarize this video: https://www.youtube.com/watch?v=n5oBmmBkW6A"  # URL from youtube_scraper test
    # YouTube URL that requires login (Should fallback to Tavily)
    test_url_msg_youtube_login = (
        "Summarize: https://www.youtube.com/watch?v=hhMXE9-JUAc"  # Test fallback
    )

    async def main():
        test_cases = {
            # "Twitter": test_url_msg_twitter,
            # "Web": test_url_msg_web,
            # "PDF": test_url_msg_pdf,
            # "Web Fail": test_url_msg_fail, # May take time
            # "LinkedIn": test_url_msg_linkedin,
            # "No URL": test_url_msg_nourl,
            # "Unsupported FTP": test_url_msg_unsupported,
            "YouTube": test_url_msg_youtube,
            # "YouTube Needs Login": test_url_msg_youtube_login,  # Test fallback (AgentQL should handle public ones)
        }

        for name, msg in test_cases.items():
            print(f"\n{'=/' * 10} RUNNING TEST: {name} {'=/' * 10}")
            print(f"Input message: {msg}")
            result = await run_agent(msg)
            print("\n--- FINAL RESULT --- ")
            if result:
                # Ensure result is treated as a string before printing
                print(str(result))
            else:
                # Handle the case where run_agent might return None (though it aims not to)
                print("Agent returned None or an empty result.")
            print(f"{'=/' * 10} FINISHED TEST: {name} {'=/' * 10}\n")

    asyncio.run(main())
