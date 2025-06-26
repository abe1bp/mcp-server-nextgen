import asyncio
import os
import json
import base64
import csv
import aiohttp
import xml.etree.ElementTree as ET
from typing import Optional, Dict, List, Any
from itertools import chain

from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
from pydantic import AnyUrl
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
import mcp.server.stdio
import logging
import sys

# Configure logging to output to both stdout and a file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("mcp_server.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# ===========================
# Configuration
# ===========================
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")
TOKEN_URL = os.getenv("OAUTH_TOKEN_URL")
BASE_URL = os.getenv("BASE_URL")
TOOLS_CSV_FILE = os.getenv("TOOLS_CSV_FILE", "workqueues.csv")

AUTOMATIONFLOW_URL = f"{BASE_URL}/automation-flows"
ACTIVITYLOG_URL = f"{BASE_URL}/automation-flows/executions"
DIGITALWORKER_URL = f"{BASE_URL}/digital-workers"
SESSION_URL = f"{BASE_URL}/sessions"

# ===========================
# In-memory data stores
# ===========================
internal_resources = {
    "automationflows": {},
    "activitylogs": {},
    "digitalworkers": {},
    "sessions": {},
    "workqueues": {},
}
resources = {
    "automationflows": {},
    "activitylogs": {},
    "digitalworkers": {},
    "sessions": {},
    "workqueues": {},
}

# ===========================
# OAuth and HTTP utilities
# ===========================
def get_access_token() -> str:
    """Fetches a new access token using client credentials."""
    try:
        client = BackendApplicationClient(client_id=CLIENT_ID)
        oauth = OAuth2Session(client=client)
        token = oauth.fetch_token(token_url=TOKEN_URL, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
        return token["access_token"]
    except Exception as e:
        logger.info(f"Error getting access token: {e}")
        raise

async def async_request(method: str, url: str, token: str, **kwargs) -> dict:
    """Performs an asynchronous HTTP request and returns JSON response."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, **kwargs) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            logger.info(f"Request failed: {e}")
            raise

def send_request(method: str, url: str, token: str, **kwargs) -> dict:
    """Performs a synchronous HTTP request (for compatibility)."""
    import requests
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.info(f"Synchronous request failed: {e}")
        raise

# ===========================
# Entity Retrieval
# ===========================
async def retrieve_entities(token: str, url: str, key: str, args: dict) -> Dict[str, Any]:
    """Fetches entities from Blue Prism and updates the internal store."""
    store = internal_resources[key]
    store.clear()
    params = {}
    if "environment" in args:
        params["environmentId.eq"] = args["environment"]

    try:
        while True:
            response = await async_request("GET", url, token, params=params)
            items = response.get("items") or response.get("value", [])
            for item in items:
                entity = item.get("entity", item)
                entity_id = entity.get("id")
                if entity_id:
                    store[entity_id] = entity

            next_token = response.get("nextPageToken") or response.get("@odata.nextLink")
            if next_token:
                if isinstance(next_token, str) and next_token.startswith("http"):
                    url = next_token
                    params = {}
                else:
                    params = {"pagetoken": next_token}
            else:
                break

        logger.info(f"Successfully retrieved {len(store)} {key}")
        return store
    except Exception as e:
        logger.info(f"Error retrieving {key}: {e}")
        return store

# ===========================
# Helper Functions
# ===========================
def create_collection_xml(fields: dict[str, str]) -> str:
    """Creates base64-encoded XML from a field dictionary."""
    collection = ET.Element("collection")
    row = ET.SubElement(collection, "row")
    for name, value in fields.items():
        ET.SubElement(row, "field", attrib={"name": name, "type": "text", "value": value})
    xml_str = ET.tostring(collection, encoding="unicode")
    return base64.b64encode(xml_str.encode("utf-8")).decode("utf-8")

def load_tools_from_csv(filepath: str) -> list[types.Tool]:
    """Loads tool definitions from a CSV file."""
    tools = []
    try:
        with open(filepath, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                tool = types.Tool(
                    name=row["name"],
                    description=row["description"],
                    inputSchema=json.loads(row["inputSchema"]),
                )
                tools.append(tool)
                internal_resources["workqueues"][row["name"]] = row
    except Exception as e:
        logger.info(f"Failed to load tools from CSV: {e}")
    return tools

def format_resource_result(store: dict[str, dict], fields: list[str]) -> str:
    """Formats resources into a pipe-delimited string table."""
    rows = []
    for key, val in store.items():
        row = [val.get(field, "") for field in fields]
        rows.append("|".join([key] + row))
    return "\n".join(rows)

# ===========================
# MCP Server setup continues...
# ===========================
...

# ===========================
# MCP Server setup
# ===========================
server = Server("mcp-server-nextgen")

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    logger.info("List resources requested")
    """Returns the list of all cached resources from internal storage."""
    results = []
    for schema, objects in resources.items():
        for id, obj in objects.items():
            try:
                name = obj.get("name", id)
                description = json.dumps(obj, indent=4, ensure_ascii=False)
                results.append(
                    types.Resource(
                        uri=AnyUrl(f"{schema}://internal/{id}"),
                        name=name,
                        description=description,
                        mimeType="text/plain",
                    )
                )
            except Exception as e:
                logger.info(f"Error processing resource {id}: {e}")
    return results

@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Fetches details of a specific resource using its URI."""
    scheme_to_url = {
        "automationflows": AUTOMATIONFLOW_URL,
        "activitylogs": ACTIVITYLOG_URL,
        "digitalworkers": DIGITALWORKER_URL,
        "sessions": SESSION_URL,
        "automationflow": AUTOMATIONFLOW_URL,
        "activitylog": ACTIVITYLOG_URL,
        "digitalworker": DIGITALWORKER_URL,
        "session": SESSION_URL,
    }
    if uri.scheme not in scheme_to_url:
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    resource_id = uri.path.lstrip("/")
    token = get_access_token()
    url = f"{scheme_to_url[uri.scheme]}/{resource_id}"
    if uri.scheme in ["activitylog", "activitylogs"]:
        url += "/logs"

    try:
        detail = await async_request("GET", url, token)
        return json.dumps(detail, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.exception("Exception occurred", exc_info=True)
        return json.dumps({"error": str(e)}, indent=4)

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    logger.info("List prompts requested")
    """Returns a list of available prompts for user input."""
    prompts = []
    if not CLIENT_ID or not CLIENT_SECRET:
        prompts.append(
            types.Prompt(
                name="Set-NextGen-Login",
                description="Configure Blue Prism Next Gen Client ID and Secret.",
                arguments=[
                    types.PromptArgument(name="id", description="Next Gen Client ID", required=True),
                    types.PromptArgument(name="secret", description="Next Gen Client Secret", required=True),
                ],
            )
        )
    return prompts

@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Optional[dict[str, str]]) -> types.GetPromptResult:
    logger.info(f"Prompt triggered: {name}")
    """Handles logic when a specific prompt is executed."""
    if name == "Set-NextGen-Login":
        global CLIENT_ID, CLIENT_SECRET
        CLIENT_ID = (arguments or {}).get("id", "")
        CLIENT_SECRET = (arguments or {}).get("secret", "")
        try:
            token = get_access_token()
            if server.request_context and server.request_context.session:
                await server.request_context.session.send_prompt_list_changed()
            return types.GetPromptResult(
                description=f"Connection information configured successfully.:{token}",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(type="text", text="Setup complete."),
                    )
                ],
            )
        except Exception as e:
            logger.exception("Exception occurred", exc_info=True)
            return types.GetPromptResult(
                description="Connection setup failed.",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(type="text", text=f"Error: {str(e)}"),
                    )
                ],
            )
    else:
        raise ValueError(f"Unknown prompt: {name}")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    logger.info("List tools requested")
    """Returns a list of fixed and dynamic tools."""
    fixed_tools = [
        types.Tool(
            name="retrieve-automation-flow-list",
            description="Retrieve the list of Automation Flows in NextGen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "environment": {
                        "type": "string",
                        "description": """Specify the environment in NextGen
                        This is not requeired property"""
                    },
                    "set_resource": {
                        "type": "boolean",
                        "description": """if 'set_resource' is True, the acquired information is registered to the resource
                        This is not requeired property"""
                    }
                },
            },
        ),
        types.Tool(
            name="start-automation-flow",
            description="Start an Automation Flow execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_flow_id": {
                        "type": "string",
                        "description": "UUID of Automation Flow",
                    }
                },
            },
        ),
        types.Tool(
            name="retrieve-activity-log-list",
            description="Retrieve the list of Activity Logs in NextGen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "environment": {
                        "type": "string",
                        "description": """Specify the environment in NextGen
                        This is not requeired property"""
                    },
                    "set_resource": {
                        "type": "boolean",
                        "description": """if 'set_resource' is True, the acquired information is registered to the resource
                        This is not requeired property"""
                    }
                },
            },
        ),
        types.Tool(
            name="retrieve-digital-worker-list",
            description="Retrieve the list of Digital Workers in NextGen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "set_resource": {
                        "type": "boolean",
                        "description": """if 'set_resource' is True, the acquired information is registered to the resource
                        This is not requeired property"""
                    }
                },
            },
        ),
        types.Tool(
            name="retrieve-session-list", 
            description="Retrieve the list of Sessions. in NextGen. ",
            inputSchema={
                "type": "object",
                "properties": {
                    "environment": {
                        "type": "string",
                        "description": """Specify the environment in NextGen
                        This is not requeired property"""
                    },
                    "set_resource": {
                        "type": "boolean",
                        "description": """if 'set_resource' is True, the acquired information is registered to the resource
                        This is not requeired property"""
                    }
                },
            },
        ),
    ]
    dynamic_tools = load_tools_from_csv(TOOLS_CSV_FILE)
    return fixed_tools + dynamic_tools

@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[dict]) -> list[types.TextContent]:
    logger.info(f"Tool called: {name}")
    """Executes the logic for a specified tool."""
    if name in internal_resources["workqueues"]:
        try:
            # Submit a work queue item based on CSV-configured parameters
            if not arguments:
                raise ValueError("Missing arguments")
            token = get_access_token()
            if not token:
                raise ValueError("Invalid Client ID or Secret")
            config = internal_resources["workqueues"][name]
            workqueue_url = f"{BASE_URL}/work-queues/{config["workqueueid"]}/items"
            
            json={
                "keyValue": config.get("keyValue", "Key0001"),
                "priority": int(config.get("priority") or "100"),
                "deferredUntil": None,
                "status": config.get("status", "Added by MCP Server"),
                "tags": [tag.strip() for tag in config.get("tags", "tag1").split(",")],
                "data": create_collection_xml(arguments),
            }

            logger.info(str(json))
            result = await async_request(
                "POST",
                workqueue_url,
                token,
                json={
                    "keyValue": config.get("keyValue", "Key0001"),
                    "priority": int(config.get("priority") or "100"),
                    "deferredUntil": None,
                    "status": config.get("status", "Added by MCP Server"),
                    "tags": [tag.strip() for tag in (config.get("tags") or "tag1").split(",")],
                    "data": create_collection_xml(arguments),
                },
            )
            return [types.TextContent(type="text", text=f"Work queue item created: {result.get('itemId')}")]
        except Exception as e:
            logger.exception("Exception occurred", exc_info=True)
            return [types.TextContent(type="text", text=f"Error creating work queue item: {str(e)}")]

    elif name == "start-automation-flow":
        try:
            # Start a specific automation flow
            if not arguments:
                raise ValueError("Missing arguments")
            token = get_access_token()
            if not token:
                raise ValueError("Invalid Client ID or Secret")
            flow_id = arguments["automation_flow_id"]
            result = await async_request("POST", f"{AUTOMATIONFLOW_URL}/{flow_id}/executions", token)
            exec_id = result.get("id", "")
            if exec_id:
                resources["activitylogs"][exec_id] = {"id": exec_id}
                if server.request_context and server.request_context.session:
                    await server.request_context.session.send_resource_list_changed()
                return [types.TextContent(type="text", text=f"Started automation flow: {exec_id}")]
            else:
                raise ValueError("Execution ID not returned")
        except Exception as e:
            logger.exception("Exception occurred", exc_info=True)
            return [types.TextContent(type="text", text=f"Error starting automation flow: {str(e)}")]

    elif name.startswith("retrieve-"):
        # Map retrieval tools to their endpoints and keys
        mapping = {
            "retrieve-automation-flow-list": (AUTOMATIONFLOW_URL, "automationflows", ["name", "description"]),
            "retrieve-activity-log-list": (ACTIVITYLOG_URL, "activitylogs", ["status", "automationFlowName"]),
            "retrieve-digital-worker-list": (DIGITALWORKER_URL, "digitalworkers", ["hostName", "status"]),
            "retrieve-session-list": (SESSION_URL, "sessions", ["status", "requestedDate"]),
        }
        if name not in mapping:
            raise ValueError(f"Unknown tool: {name}")
        args = {}
        if arguments:
            args = arguments
        url, key, fields = mapping[name]
        try:
            token = get_access_token()
            if not token:
                raise ValueError("Invalid Client ID or Secret")
            updated_store = await retrieve_entities(token, url, key, args)
            if server.request_context and server.request_context.session:
                await server.request_context.session.send_resource_list_changed()
            result_text = format_resource_result(updated_store, fields)
            if arguments.get("set_resource"):
                resources[key] = internal_resources[key].copy()
                return [types.TextContent(
                    type="text",
                    text=f"Resource refreshed. Retrieved {len(updated_store)} {key}.\n{result_text}"
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text=f"Retrieved {len(updated_store)} {key}.\n{result_text}"
                )]
                
        except Exception as e:
            logger.exception("Exception occurred", exc_info=True)
            return [types.TextContent(
                type="text",
                text=f"Error {key}: {str(e)}"
            )]

    else:
        raise ValueError(f"Unknown tool: {name}")

# ===========================
# Entry Point
# ===========================
async def main():
    """Starts the MCP server and initializes resources."""
    logger.info('Starting MCP server...')
    load_tools_from_csv(TOOLS_CSV_FILE)
    logger.info("Server initialized, starting main loop...")
    if not TOKEN_URL or not BASE_URL:
        raise ValueError("Enviroment variables not set.")
        # Security consideration: Ensure only trusted clients can connect via stdio.
        # Avoid processing arbitrary or untrusted inputs without validation.
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        # Ensure handlers validate and sanitize all incoming request content to avoid injection attacks.
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp-server-nextgen",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )