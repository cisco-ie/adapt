# ADAPT

AI-Driven Action Planner & Troubleshooter (ADAPT)

## Requirements

- Python 3.12 and above
- Docker (optional, for containerized deployment)
- LangGraph and PydanticAI libraries
- Netmiko for network device communication
- HTTPX for async HTTP requests
- Streamlit for the user interface

## Overview

ADAPT is an autonomous network troubleshooting system that uses AI-driven agents to diagnose and solve network issues. The system utilizes a multi-agent workflow powered by LangGraph and PydanticAI to provide intelligent, step-by-step troubleshooting of network problems.

The workflow consists of the following AI agents:

1. **Fault Summarizer**: Analyzes network alerts and summarizes the issue
2. **Action Planner**: Creates a detailed troubleshooting plan with specific commands
3. **Action Executor**: Executes commands on network devices (real or simulated)
4. **Action Analyzer**: Analyzes command outputs and determines next steps
5. **Result Summary**: Provides a comprehensive troubleshooting report

## Setup

### Option 1: Python Native with Virtual Environment

1. Clone this repository
2. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate  # Windows
   # OR
   source venv/bin/activate  # Linux/Mac
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Create a `.env` file with your configurations (copy from .env.example):
   ```
   copy .env.example .env  # Windows
   # OR
   cp .env.example .env  # Linux/Mac
   ```
5. Update the `.env` file with your settings:
   ```
   # API settings
   BASE_URL=https://api.openai.com/v1
   OPENAI_API_KEY=your_api_key_here
   LOGFIRE_TOKEN=your_logfire_token_here (optional)
   
   # Device credentials
   DEVICE_USERNAME=admin
   DEVICE_PASSWORD=password
   DEVICE_SECRET=enable_password
   
   # Configuration paths
   INVENTORY_PATH=configuration/inventory.yml
   ```

### Option 2: Docker Compose

1. Clone this repository

2. **Prerequisites**:
   - [Docker](https://www.docker.com/get-started) installed on your system

3. **Environment Variables Configuration**:
   - Copy the example environment file to create your own:
     ```
     copy .env.example .env
     ```
   - Edit the `.env` file with your configuration values:
     ```
     OPENAI_API_KEY=your_api_key_here
     ```
     - Configure any device hostname, type, and port settings
     - Add any other environment variables needed by the application

4. **Build and run** with Docker Compose:
   ```
   docker compose up -d
   ```
   
   To rebuild after code changes:
   ```
   docker compose up --build -d
   ```
   
   To stop the container:
   ```
   docker compose down
   ```

5. **Mounted Volumes**:
   The following directories are mounted from the host into the container:
   - **./workbench:/app/workbench**: For persistent data storage
   - **./configuration:/app/configuration**: For device inventories and settings files

   Any changes made to these directories on the host will be immediately reflected in the container.

## Running the Application

### Python Native
Launch the Streamlit application:

```
streamlit run streamlit_app.py
```

### Docker
When using Docker, the application runs automatically with the following services:

- **Streamlit Application**: Accessible at `http://localhost:8501`
- **Alert Queue Service**: Exposed on port 8001 (can be started through the Streamlit interface when needed)

### Alert Queue API

ADAPT provides an API endpoint for receiving network alerts:

- **Endpoint**: `POST /alert`
- **Port**: 8001 (default)
- **Input**: Any valid JSON content
- **Response**: Success or error message

To send an alert manually:

```
curl -X POST http://localhost:8001/alert -H "Content-Type: application/json" -d '{"alert_id":"BGPDOWN-0001","device":"NCS5508-1","severity":"high","message":"BGP neighbor 1.2.3.4 is Down","raw_event":"%ROUTING-BGP-5-ADJCHANGE : neighbor 1.2.3.4 - Hold timer expired"}'
```

## Project Structure

- `agents/`: Directory containing all agent implementations
  - `hello_world/`: Hello World agent implementation
  - `fault_summary/`: Fault Summary agent implementation
  - `action_planner/`: Action Planning agent implementation
  - `action_executor/`: Command execution agent implementation
  - `action_analyzer/`: Output analysis agent implementation
  - `result_summary/`: Result Summary agent implementation
- `configuration/`: Settings and network device inventory
  - `inventory.yml`: Network device inventory
  - `settings.yml`: Application settings
- `graph.py`: LangGraph implementation for the multi-agent workflow
- `static/`: Directory for files served via direct URLs
- `streamlit_app.py`: Main Streamlit application
- `tests/`: Test scenarios for simulation mode
- `utils/`: Utility functions and helpers
- `workbench/`: Storage for troubleshooting session logs
- `alert_queue.py`: API service for receiving network alerts

## Features

- **Multiple Operation Modes**:
  - **Simulation Mode**: Run commands without actual execution on devices
  - **Test Mode**: Use predefined test data from YAML files
  - **Production Mode**: Connect to and execute commands on real network devices

- **Golden Rules**: Configure safety rules that are always followed by agents
  - Edit the `golden_rules` section in `settings.yml` to add or modify rules
  - Rules are enforced during the generation of troubleshooting steps

- **Direct Result Access**: Troubleshooting results and response logs are saved as files with direct URL links for easy access and integration with other systems

- **Multi-Agent Workflow**: End-to-end troubleshooting using multiple specialized agents

- **Approval System**: Critical commands can be configured to require explicit user approval

- **Individual Agent Testing**: Each agent can be tested independently through the UI

- **Step Mode**: When enabled, requires approval before proceeding to the each step in the workflow

- **Custom Instructions**: Add specific set of custom instructions for a known issue.  These instructions will heavily influence that agent's behavior when generating troubleshooting steps.

- **Adaptive Mode**: When enabled, allows the system to adapt modify the action plan based upon findings from previous steps in the workflow.  This allows the system to dynamically adjust its approach based on results.

## Configuration

### Test Scenarios

Test scenarios are defined in YAML files in the `tests/` directory. Each file contains:

- `alert_payload`: The simulated alert that triggers the workflow
- `custom_instructions`: Specific remediation guidelines for this scenario
- `command_outputs`: Simulated outputs for various network commands

To create a new test scenario, copy an existing file and modify it, or use the `utils/generate_test.py` script to generate a test scenario using a Test Generation AI Agent.

### Settings

The `settings.yml` file in the `configuration/` directory contains various settings:

- `debug_mode`: Enable verbose logging for debugging (currently unsupported)
- `simulation_mode`: Use LLM to simulate command outputs instead of executing them on devices
- `test_mode`: Use predefined test data from YAML files
- `test_name`: The name of the test file to use in test mode
- `step_mode`: Require approval between workflow steps
- `adaptive_mode`: Allow the system to adapt its troubleshooting action plan based on results
- `golden_rules`: Global rules that agents must follow
- `max_steps`: Maximum number of troubleshooting steps allowed in an action plan
- `custom_instructions`: Remediation guide for known issues

### Network Device Inventory

The `inventory.yml` file in the `configuration/` directory defines network devices:

```yaml
devices:
  DEVICE-NAME:
    hostname: "device_ip_address"
    device_type: "cisco_xr"  # Netmiko driver type
    username: "username"  # Default from .env if not specified
    password: "password"  # Default from .env if not specified
    optional_args:
      port: 22
      transport: "ssh"
      timeout: 60
```

## Observability

ADAPT optionally integrates with Logfire for observability and API usage tracking. To enable this feature:

1. Get your token from [https://logfire.pydantic.dev](https://logfire.pydantic.dev)
2. Add it to your `.env` file:
   ```
   LOGFIRE_TOKEN=your_logfire_token_here
   ```

## Roadmap and Known Issues

See the [CHANGELOG.md](./CHANGELOG.md) for a list of known issues and planned improvements for upcoming releases.

## Contributing

We welcome contributions to ADAPT! Here's how you can contribute:

1. **Fork the repository** on GitHub
2. **Create a branch** for your changes
3. **Make your changes** (new agents, bug fixes, documentation, etc.)
4. **Submit a pull request** back to the main repository

For questions or suggestions, please open an issue on GitHub.

