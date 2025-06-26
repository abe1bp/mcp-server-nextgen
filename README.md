# 🧾 MCP Server for SS&C Next Generation

This project provides an MCP-compatible server that connects AI agents to SS&C Next Generation, enabling automated execution of business processes via the REST API.

Designed with flexibility in mind, this server allows you to:

Easily define and manage tools using a simple CSV configuration, without modifying source code.

Automatically submit items to Work Queues, a key component of Next Gen RPA orchestration.

Trigger automation flows in response to new queue items, creating a seamless bridge between AI-driven decisions and RPA actions.

Whether you're integrating conversational agents, scheduling systems, or custom applications, this server gives you a low-code interface to dynamically register actions and automate task submission with minimal overhead.

## 🚀 Installation & Setup

This section helps you set up and run an MCP-compatible server that interacts with **SS&C Next Gen REST API**.

### 🔧 Prerequisites

- Python 3.10 or later
- `uv` (recommended) package manager
- MCP-compatible client (e.g., Claude Desktop)
- SS&C Next Generation Environment([Japanese](https://www.blueprism.com/japan/products/next-generation/)/[English](https://www.blueprism.com/products/next-generation/))
---

### 📥 Installation Steps

1. **Prepare Next Generation Service Account**

Refer to the link below to create a service account.

[Service Account](https://docs.blueprism.com/en-US/bundle/next-generation/page/access/service-accounts.htm)

2. **Prepare Next Generation Work Queue**
  
Work queue preparation is required when using dynamic tools.
Please refer to the following link to create a work queue.

[Work Queues](https://docs.blueprism.com/en-US/bundle/next-generation/page/control-center/work-queues.htm)

When combining with automated processing, it is necessary to check the following Automation Flow information and link it to the work queue

[Automation Flow](https://docs.blueprism.com/en-US/bundle/next-generation/page/control-center/automation-flows.htm)

3. **Prepare the project directory**

```bash
git clone https://github.com/abe1bp/mcp-server-nextgen.git
cd mcp-server-nextgen
```
---

## ⚙️ Add MCP Server to `claude_desktop_config.json`

To connect Claude Desktop to your server, add:

```jsonc
{
  "mcpServers": {
    "mcp-server-nextgen": {
      "command": "uv",
      "args": [
        "--directory",
        "{folder path}",
        "run",
        "mcp-server-nextgen"
      ],
      "env": {
        "OAUTH_CLIENT_ID": "{your-client-id}",
        "OAUTH_CLIENT_SECRET": "{your-client-secret}",
        "OAUTH_TOKEN_URL": "https://{tenant-domain}/realms/{tenant-id}/protocol/openid-connect/token",
        "BASE_URL": "https://{tenant-domain}/regions/{region}/api/rpa/rest/v1"
      }
    }
  }
}
```
{folder path} is the folder prepared in Prepare the project directory.

Cconfigure the {your-client-id} and {your-client-secret} of the Service Account created in Step 1 of the Installation Steps.

For each URL parameters, please refer to the links provided below.
[**Next Generation REST API**](https://docs.blueprism.com/en-US/bundle/next-generation/page/rest-api.htm)
Then restart Claude Desktop and select `mcp-server-nextgen`.

---

## 📌 Purpose

This Python-based MCP server leverages the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol/mcp) to:

- Connect to [**Next Generation REST API**](https://docs.blueprism.com/en-US/bundle/next-generation/page/rest-api.htm)
- Authenticate via OAuth2 and expose secure MCP endpoints
- Dynamically define tools to submit items to Next Generation Work Queues

---

## 📁 Key Components

## 🛠 Tool Types

### 🧩 Retrive Tools (predefined)

- `retrieve-automation-flow-list`
- `retrieve-activity-log-list`
- `retrieve-digital-worker-list`
- `retrieve-session-list`


### 🧩 Start automation flow Tool (predefined)
- `start-automation-flow`

---

### 📄 Dynamic Tools (CSV-defined)

#### CSV Configuration for Dynamic Tool Loading

The `workqueues.csv` file defines tools that are dynamically loaded at server startup. Each row in the CSV represents a tool that can **submit an item to a specific work queue**.

##### Column Descriptions

Here is a clearer breakdown of the required columns:

| Column        | Required | Description                                                                                                                                                  |
| ------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `workqueueid` | Yes      | The unique identifier (UUID format) of the work queue where the item will be submitted.                                                                      |
| `name`        | Yes      | A short, unique identifier for the tool. Used as its registered name.                                                                                        |
| `description` | Yes      | A brief explanation of what the tool does. Displayed to clients and used to assist tool discovery.                                                           |
| `inputSchema` | Yes      | A JSON Schema (as a string) defining the input structure required by the tool. Each input parameter must include a `description` to be usable by the client. |
| `keyValue`    | No       | A key or identifier that will be passed to the queue item (e.g., an Order ID). Can be a fixed value or a reference.                                          |
| `priority`    | No       | An integer indicating the priority of the submitted item (e.g., 0 = lowest, 100 = highest).                                                                  |
| `status`      | No       | Initial status assigned to the item when submitted (e.g., `New`, `Pending`).                                                                                 |
| `tags`        | No       | Comma-separated tags to help categorize or filter items in the queue.                                                                                        |

##### Example

```csv
workqueueid,name,description,inputSchema,keyValue,priority,status,tags
aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,submit-order,"Submit an order",{"type":"object","properties":{"OrderId":{"type":"string","description":"Order ID"}}},"Order001",50,"New","order,urgent"
```

##### Notes

* Make sure `inputSchema` is a valid JSON object serialized as a string.
* The `description` fields within `inputSchema` are essential for UI rendering and interaction.
* You can omit optional columns if not needed, but headers must still be present.

This format allows you to configure and register dynamic tools for queue submissions without code changes.


📌 **Dynamic tools are flexible**:
- You can define multiple tools per work queue.
- Set proper `name`, `description`, `inputSchema`, and parameters to trigger item submission only when needed.

---

## 📤 Prompts

This is used when Client id and Client Secret are not set as environment variables.

| Prompt Name        | Purpose                             |
|--------------------|-------------------------------------|
| Set-NextGen-Login  | Set Client ID / Secret manually     |

---

## 🧪 Example: Tool Execution

### ✅ Call `retrieve-digital-worker-list`

Returns the list of digital workers and updates MCP clients via `resources_changed`.

### ✅ Call `submit-order` (CSV-defined tool)

Posts an item to a work queue:

```json
{
  "keyValue": "Order001",
  "priority": 50,
  "status": "New",
  "tags": ["order", "urgent"],
  "data": "<base64-encoded XML>"
}
```



---
