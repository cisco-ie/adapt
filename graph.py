"""
LangGraph implementation for connecting the PydanticAI agents in a workflow.

This module creates a graph that connects all agents in the following order:
1. Fault_summary
2. Action_planner
3. Action_executor
4. Action_analyzer
"""

from __future__ import annotations
from typing import TypedDict, List, Dict, Any, Optional, Annotated, Literal
from dataclasses import dataclass
from datetime import datetime
import os
import logging
import asyncio
import yaml
import json
from pathlib import Path

from dotenv import load_dotenv
from netmiko import ConnectHandler
from pydantic import BaseModel, Field
from utils.netmiko_utils import parse_device_facts, get_interface_list
from langgraph.types import interrupt, Command
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from httpx import AsyncClient

# Import agents
from agents.fault_summary import run as run_fault_summary
from agents.action_planner import run as run_action_planner
from agents.action_executor import run as run_action_executor
from agents.action_analyzer import run as run_action_analyzer
from agents.result_summary import run as run_result_summary

# Import models from the central models.py file
from agents.models import (
    FaultSummary, 
    TroubleshootingStep,
    ActionAnalysisReport, 
    FaultSummaryDependencies, 
    ActionPlannerDependencies,
    ActionExecutorDeps,
    ActionAnalyzerDependencies,
    ResultSummaryDependencies,
    ResultSummary
)

# Load environment variables
load_dotenv()

# Global variable for Netmiko connection
# Will be initialized in run_init_deps_node and passed to run_action_executor_node
NETMIKO_CONNECTION = None

# Path to the network device inventory YAML file
inventory_path = os.getenv("INVENTORY_PATH", "configuration/inventory.yml")
# Path to the settings YAML file
settings_path = os.getenv("SETTINGS_PATH", "configuration/settings.yml")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_settings(file_path: str) -> Dict[str, Any]:
    """
    Load application settings from a YAML file.
    
    This function reads configuration settings from a YAML file into a Python dictionary.
    Settings include debug_mode, simulation_mode, test_mode, test_name, max_steps, and golden_rules.
    
    Args:
        file_path: Path to the YAML file containing settings
        
    Returns:
        Dict[str, Any]: Dictionary containing application settings
        
    If the settings file doesn't exist or can't be loaded, default settings will be returned.
    """
    default_settings = {
        "debug_mode": False,
        "simulation_mode": True,
        "test_mode": False,
        "test_name": "",
        "max_steps": 15,
        "golden_rules": []
    }
    
    try:
        if not os.path.exists(file_path):
            logger.warning(f"Settings file {file_path} not found, using defaults")
            return default_settings
            
        with open(file_path, 'r') as file:
            settings = yaml.safe_load(file)
            
        # Ensure all expected settings are present
        for key in default_settings:
            if key not in settings:
                settings[key] = default_settings[key]
                
        logger.info(f"Loaded settings from {file_path}")
        return settings
    except Exception as e:
        logger.error(f"Error loading settings: {str(e)}")
        return default_settings

def load_network_inventory(file_path: str) -> Dict[str, Any]:
    """
    Load network device inventory from a YAML file.
    
    This function reads in the details of a network device inventory
    from a YAML file into a Python dictionary. The inventory contains
    information about network devices such as hostname, IP address,
    device type, credentials, etc.
    
    Args:
        file_path: Path to the YAML file containing network inventory
        
    Returns:
        Dict[str, Any]: Dictionary containing network device inventory
        
    Loads credentials from environment variables if not specified in the inventory.
    Validates required fields for Netmiko device connection.
    """
    default_inventory = {"devices": {}}
    
    try:
        if not os.path.exists(file_path):
            logger.warning(f"Inventory file {file_path} not found, using default empty inventory")
            return default_inventory
            
        with open(file_path, 'r') as file:
            inventory = yaml.safe_load(file)
            
        # Ensure the expected structure exists
        if "devices" not in inventory:
            logger.warning("Inventory file missing 'devices' section, using default empty inventory")
            return default_inventory
            
        # Load defaults from environment variables
        default_username = os.getenv("DEVICE_USERNAME", "")
        default_password = os.getenv("DEVICE_PASSWORD", "")
        default_secret = os.getenv("DEVICE_SECRET", "")
        
        # Apply environment variable defaults to any device missing credentials
        for device_name, device_data in inventory["devices"].items():
            # Apply username from env if not in device config
            if not device_data.get("username"):
                device_data["username"] = default_username
                
            # Apply password from env if not in device config
            if not device_data.get("password"):
                device_data["password"] = default_password
                
            # Apply secret to optional_args if needed
            if "optional_args" in device_data:
                if "secret" not in device_data["optional_args"] or not device_data["optional_args"]["secret"]:
                    device_data["optional_args"]["secret"] = default_secret
        
        logger.info(f"Loaded inventory from {file_path} with {len(inventory['devices'])} devices")
        return inventory
    except Exception as e:
        logger.error(f"Error loading inventory: {str(e)}")
        return default_inventory

# Load network inventory
network_inventory = load_network_inventory(inventory_path)

# Define the state for our graph
class NetworkTroubleshootingState(TypedDict):
    """State for the network troubleshooting workflow graph."""
    latest_user_message: str
    messages: Annotated[List[bytes], lambda x, y: x + y]
    inventory: Dict[str, Any]
    alert_raw_data: str
    fault_summary: Optional[FaultSummary]
    action_plan: Optional[List[TroubleshootingStep]]
    action_plan_history: Optional[List[TroubleshootingStep]]  
    action_plan_remaining: Optional[List[TroubleshootingStep]]
    current_step_index: int
    current_step: TroubleshootingStep
    action_executor_history: List[Dict[str, Any]]
    execution_result: Optional[Dict[str, Any]]
    analysis_report: Optional[ActionAnalysisReport]
    device_facts: Dict[str, Any]  # Device facts including reachability information
    settings: Dict[str, Any]  # Contains simulation_mode, test_mode, test_name, etc.
    test_data: Optional[Dict[str, Any]]  # Store loaded test data


# Function to load test data
def load_test_data(test_name: str) -> Dict[str, Any]:
    """Load test data from a YAML file."""
    try:
        test_file = Path(f"tests/test_{test_name}.yml")
        if not test_file.exists():
            logger.warning(f"Test file {test_file} not found")
            return {}
        
        with open(test_file, "r") as f:
            test_data = yaml.safe_load(f)
        
        logger.info(f"Loaded test data for {test_name}")
        return test_data
    except Exception as e:
        logger.error(f"Error loading test data: {e}")
        return {}

# Function to run the fault summary agent
async def run_fault_summary_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Run the fault summary agent to analyze and summarize a network fault."""
    logger.info("Running fault summary agent")
    
    # Get the input text and settings from the state
    alert_raw_data = state["latest_user_message"]
    settings = state["settings"]
    test_data = {}
    
    # Handle test mode - load test data if test_mode is enabled
    if settings.get("test_mode", False):
        test_name = settings.get("test_name", "")
        if test_name:
            test_data = load_test_data(test_name)
            if test_data:
                if "alert_payload" in test_data:
                    # Use the test alert payload as input instead of user message
                    alert_raw_data = test_data["alert_payload"]
                    logger.info(f"Using test alert payload from test_{test_name}.yml")
    
    # Create dependencies for the fault summary agent
    fault_summary_deps = FaultSummaryDependencies(
        settings=settings,
        logger=logger
    )
      # Run the fault summary agent with dependencies
    result = await run_fault_summary(alert_raw_data, deps=fault_summary_deps)
    fault_summary = result.output

    # Generate output showing the raw alert that was received and display fault summary
    writer(f"""## 🚨 Alert Received

The following alert has been received:
```
{alert_raw_data}
```

## 📊 Fault Summary

**Title:** {fault_summary.title}  
**Summary:** {fault_summary.summary}  
**Device:** {fault_summary.hostname}  
**Severity:** {fault_summary.severity}  
**Timestamp:** {fault_summary.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  
**Additional Metadata:** {fault_summary.metadata}
""")

    # Update the state with the fault summary and test data if available
    return {
        **state,
        "alert_raw_data": alert_raw_data,
        "fault_summary": fault_summary,
        "test_data": test_data
    }

# Function to run the init_deps node for dependency initialization
async def run_init_deps_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Initialize device dependencies before running the action planner."""
    logger.info("Running init_deps node")
      # Get settings and fault_summary from state
    settings = state["settings"]
    fault_summary = state["fault_summary"]
    test_data = state.get("test_data", {})
    inventory = load_network_inventory(inventory_path)  # Load network inventory
    
    # Initialize device_facts with default values
    device_facts = {
        "reachable": True,
        "errors": []
    }    
      # Access the global Netmiko connection
    global NETMIKO_CONNECTION
    
    # Only perform actual device connection when not in simulation or test mode
    if not settings.get("simulation_mode", True) and not settings.get("test_mode", False):
        try:
            # Get hostname from fault summary
            hostname = fault_summary.hostname
            
            # Look up device details in inventory
            device_details = inventory.get("devices", {}).get(hostname, {})
            
            if not device_details:
                logger.warning(f"Device {hostname} not found in inventory")
                device_facts["reachable"] = False
                device_facts["errors"].append(f"Device {hostname} not found in inventory")
            else:
                try:                    # Get device type from inventory
                    device_type = device_details.get("device_type")
                    if not device_type:
                        raise ValueError(f"Device type not specified for {hostname}")

                    # Get connection parameters
                    host = device_details.get("hostname")
                    username = device_details.get("username")
                    password = device_details.get("password")
                    optional_args = device_details.get("optional_args", {})
                    
                    # Close the existing connection if it's already open
                    if NETMIKO_CONNECTION:
                        try:
                            NETMIKO_CONNECTION.disconnect()
                            logger.info(f"Closed existing Netmiko connection before creating a new one")
                        except Exception as e:
                            # Do nothing because the connection has probably already been closed
                            pass       
                                 
                    # Create a device dictionary for Netmiko
                    device_dict = {
                        'device_type': device_type,
                        'host': host,
                        'username': username,
                        'password': password,
                        'port': optional_args.get('port', 22),
                    }
                    
                    # Add optional secret if it exists
                    if 'secret' in optional_args and optional_args['secret']:
                        device_dict['secret'] = optional_args['secret']
                    
                    # Initialize the global Netmiko connection
                    NETMIKO_CONNECTION = ConnectHandler(**device_dict)
                      # Get device facts using Netmiko commands
                    facts = {}
                    try:
                        # Get hostname
                        output = NETMIKO_CONNECTION.send_command('show version')
                        facts['hostname'] = hostname
                        
                        # Parse facts based on device type
                        parsed_facts = parse_device_facts(device_type, output)
                        facts.update(parsed_facts)
                        
                        # Get interfaces using helper function
                        facts['interface_list'] = get_interface_list(NETMIKO_CONNECTION, device_type)
                                    
                        # Default fallback - use what we have                        
                        if 'fqdn' not in facts:
                            facts['fqdn'] = f"{hostname}.example.com"  # Default placeholder
                        
                    except Exception as e:
                        logger.warning(f"Error getting detailed facts: {str(e)}. Using basic facts.")
                    
                    # Update device_facts with what we gathered
                    device_facts.update(facts)
                    
                    # Add os, reachable, and errors fields
                    device_facts["os"] = device_details.get("device_type")
                    device_facts["reachable"] = True
                    device_facts["errors"] = []
                    
                    # Don't close the connection - keep it open for later use
                    
                    # Log successful connection
                    logger.info(f"Successfully connected to {hostname}")
                except Exception as e:
                    error_message = f"Failed to initialize Netmiko driver: {str(e)}"
                    logger.error(error_message)
                    device_facts["reachable"] = False
                    device_facts["errors"].append(error_message)
                
        except Exception as e:
            # Handle connection failures
            error_message = f"Failed to connect to device: {str(e)}"
            logger.error(error_message)
              # Update device_facts to indicate unreachable
            device_facts["reachable"] = False
            device_facts["errors"].append(error_message)
    else:
        # Simulation mode or test mode
        hostname = fault_summary.hostname
        # If in test_mode and test_data contains device_facts, use those
        if settings.get("test_mode", False) and test_data and "device_facts" in test_data:
            device_facts = test_data["device_facts"]
        else:
            # Simulation mode - create simulated facts
            device_facts = {
                "hostname": hostname,
                "vendor": "cisco",
                "model": "CSR1000v",
                "uptime": 12345,
                "os_version": "16.9.3",
                "serial_number": "9KLAVM0JJ62",
                "interface_list": ["GigabitEthernet0/0", "GigabitEthernet0/1", "Loopback0"],
                "fqdn": f"{hostname}.example.com",
                "os": "ios",
                "reachable": True,
                "errors": []
            } 
          # Set global connection to None in simulation or test mode
        NETMIKO_CONNECTION = None
    
    # Generate output for the writer
    if device_facts["reachable"]:
        status = "✅ Device reachable"
    else:
        status = "❌ Device unreachable"
    
    # Create a formatted output of device facts for the writer
    facts_output = ""
    for key, value in device_facts.items():
        if key != "errors":  # We're handling errors separately
            facts_output += f"- **{key}:** {value}\n"
    
    writer(f"""## 🔌 Device Dependency Initialization

**Device:** {fault_summary.hostname}
**Status:** {status}

### Device Facts:
{facts_output}

{"### Errors:" if device_facts["errors"] else ""}
{"".join([f"- {error}\n" for error in device_facts["errors"]])}
""")    
    # Update the state with the initialized dependencies
    return {
        **state,
        "inventory": inventory,
        "device_facts": device_facts
    }

# Function to run the action planner agent
async def run_action_planner_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Run the action planner agent to create a troubleshooting plan."""
    logger.info("Running action planner agent")
    # Get the fault summary from the state
    fault_summary = state["fault_summary"]
    device_facts = state["device_facts"]
    settings = state["settings"]
    # Use custom_instructions from settings if present
    custom_instructions = settings.get("custom_instructions", "")
    test_data = state.get("test_data", {})
    
    if not fault_summary:
        logger.warning("No fault summary found in state")
        return state
    
    # Handle test mode - load test data if test_mode is enabled
    if settings.get("test_mode", False) and test_data:
        if "custom_instructions" in test_data:
            # Use custom instructions from test data if provided
            custom_instructions = test_data["custom_instructions"]
            logger.info(f"Using custom instructions from test_{settings['test_name']}.yml")

    # Create dependencies for the action planner
    deps = ActionPlannerDependencies(
        fault_summary=fault_summary,
        custom_instructions=custom_instructions,
        device_facts=device_facts,
        settings=settings,
        logger=logger
    )
    
    # Run the action planner agent with the dependencies
    result = await run_action_planner("", deps=deps)
    action_plan = result.output    # Generate human-readable output for the writer with Markdown formatting
    steps_markdown = []
    for i, step in enumerate(action_plan):
        # Format commands as a bulleted list
        commands_list = "\n".join([f"  - `{cmd}`" for cmd in step.commands]) if step.commands else "  - None"
        
        steps_markdown.append(f"""### Step {i+1}: {step.description}
- **🔄 Action Type:** {step.action_type}
- **📟 Commands:** 
{commands_list}
- **🔍 Expected Output:** {step.output_expectation}
- **⚠️ Requires Approval:** {'Yes' if step.requires_approval else 'No'}
""")
    
    # Add note about custom instructions if they exist
    custom_instructions_section = ""
    if custom_instructions:
        custom_instructions_section = f"""\n\n### ⚠️ Note: Custom Instructions Applied

The following custom instructions have been identified for this fault and integrated into the action plan:

```
{custom_instructions}
```

"""
    
    writer(f"""

{custom_instructions_section}

## 🔍 Action Plan

**Total Steps:** {len(action_plan)}

{''.join(steps_markdown)}
""")
    
    # Update the state with the action plan and set current step to 0
    return {
        **state,
        "action_plan": action_plan,
        "action_plan_remaining": action_plan,
        "action_plan_history": [],
        "current_step_index": 0,
    }

async def run_action_router_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState | Command[Literal["action_executor", "result_summary"]]:
    """Router node that manages action plan workflow and handles approval requirements."""
    logger.info("Running action router node")
    
    # 1. Update action_plan_history by appending the latest executed step
    action_plan_history = state.get("action_plan_history", [])
    action_plan_remaining = state.get("action_plan_remaining", [])
    settings = state.get("settings", {})

    current_step= state.get("current_step", None)
    current_step_index = state.get("current_step_index", 0)
    
    # 2. If there is a current_step and an analysis report, add the executed step to history and set next_action_type
    if current_step and current_step.analysis_report:
        action_plan_history.append(current_step)
        # Increment the current step index to move to the next step
        next_action_type = current_step.analysis_report.next_action_type

        # 3. If next_action_type is "resolve" or "escalate", route to result summary
        if next_action_type == "escalate":
            writer("\n⚠️ **Escalation detected. Routing to result summary.**\n")
            # Use Command to route to the result_summary node
            return Command(
                update={
                    "action_plan_history": action_plan_history,
                },
                goto="result_summary"
            )
        elif next_action_type == "resolve":
            writer("\n✅ **Resolution detected. Routing to result summary.**\n")
            # Use Command to route to the result_summary node
            return Command(
                update={
                    "action_plan_history": action_plan_history,
                },
                goto="result_summary"
            )
        else:
            # Increment step index to indicate that we will move to the next step in the action plan
            current_step_index += 1
            # Check if max_steps limit has been exceeded
            max_steps = settings.get("max_steps", 15)
            if current_step_index > max_steps:
                logger.warning(f"Maximum step count of {max_steps} has been exceeded")
                writer(f"\n⚠️ **Maximum step count of {max_steps} has been exceeded. Escalating for human intervention.**\n")
                
                if current_step:
                    # Create an analysis report to indicate the step limit was exceeded
                    current_step.analysis_report = ActionAnalysisReport(
                        analysis=f"Maximum step count of {max_steps} has been exceeded",
                        findings=[f"Workflow exceeded maximum allowed steps ({max_steps})"],
                        next_action_type="escalate",
                        next_action_reason=f"Maximum step count of {max_steps} has been exceeded. Escalating for human intervention."
                    )
                    action_plan_history.append(current_step)
                
                # Route to result_summary
                return Command(
                    update={
                        "action_plan_history": action_plan_history,
                    },
                    goto="result_summary"
                )

    # Check if we have steps remaining
    if not action_plan_remaining:
        writer("⚠️ **No more steps to execute. Routing to result summary.**")
        # Use Command to route to the result_summary node
        return Command(
            update={
                "action_plan_history": action_plan_history,
                "action_plan_remaining": action_plan_remaining,
                "current_step": current_step
            },
            goto="result_summary"
        )
    
    # 3. Check device reachability
    device_facts = state["device_facts"]
    if not device_facts.get("reachable", False):
        writer("⚠️ **Device is unreachable. Routing to result summary.**")
        # Use Command to route to the result_summary node
        return Command(
            update={
                "action_plan_history": action_plan_history,
                "action_plan_remaining": action_plan_remaining,
                "current_step_index": current_step_index,
                "current_step": current_step
            },
            goto="result_summary"
        )
    
    # 4. Get current_step
    current_step = action_plan_remaining[0]
    # Remove the current step from the remaining steps
    action_plan_remaining = action_plan_remaining[1:]
    # Set current_step in state for persistence during human interrupt
    state["current_step"] = current_step
    
    # 5. Write step details for review
    commands_text = "\n".join([f"- `{cmd}`" for cmd in current_step.commands]) if current_step.commands else "- No commands"
    # TODO: Update this to use the same format as the action analyzer
    writer(f"""## ⚡ Executing Step {current_step_index + 1}
    
**Step Description:** {current_step.description}

**Action Type:** {current_step.action_type}

**Commands to Execute:**
{commands_text}

**Expected Output:** {current_step.output_expectation}

**Requires Approval:** {"Yes" if current_step.requires_approval else "No"}
""")
    
    # 6. If action type is escalation, route to result summary
    if current_step.action_type == "escalation":
        writer("⚠️ **Escalation step detected. Routing to result summary.**")
        # Set current_step.analysis_report to reflect the escalation
        current_step.analysis_report = ActionAnalysisReport(
            analysis="No analysis performed due to escalation",
            findings=[],
            next_action_type="escalate",
            next_action_reason="",
        )
        
        action_plan_history.append(current_step)
        # Use Command to route to the result_summary node
        return Command(
            update={
                "action_plan_history": action_plan_history,
                "action_plan_remaining": action_plan_remaining,
                "current_step_index": current_step_index,
                "current_step": current_step
            },
            goto="result_summary"
        )


    # 6. Check if approval is required and prompt user if needed
    if current_step.requires_approval:
        writer("\n\n⚠️ **This step requires approval. Waiting for user confirmation...**")
        # Please respond with "yes" or "no" to approve or reject the action
        writer("\n**Please respond with *yes* or *no* to approve or reject the action.**\n\n")

        # Create a list of valid "yes" responses
        yes_responses = ["yes", "y", "true", "approve", "1"]
        # Create a list of valid "no" responses
        no_responses = ["no", "n", "false", "reject", "0"]
        # While loop to ensure valid response
        response = None
        while response not in yes_responses and response not in no_responses:

            # Use interrupt to retrieve response from user
            response_text = interrupt({})
            
            # 7-8. Handle user approval response
            if response_text.lower().strip() in yes_responses:
                writer("✅ **Action approved by user. Proceeding to execution.**\n\n")
                return Command(
                    update={
                        "action_plan_history": action_plan_history,
                        "action_plan_remaining": action_plan_remaining,
                        "current_step_index": current_step_index,
                        "current_step": current_step
                    },
                    goto="action_executor"
                )
            elif response_text.lower().strip() in no_responses:
                writer("🛑 **Action rejected by user. Routing to result summary.**\n\n")
                current_step.analysis_report = ActionAnalysisReport(
                    analysis="No analysis performed due to action being rejected by user.",
                    findings=[],
                    next_action_type="escalate",
                    next_action_reason="Action rejected by user.",
                )
            
                action_plan_history.append(current_step)
                return Command(
                    update={
                        "action_plan_history": action_plan_history,
                        "action_plan_remaining": action_plan_remaining,
                        "current_step_index": current_step_index,
                        "current_step": current_step
                    },
                    goto="result_summary"
                )
            else:
                writer("❌ **Invalid response. Please respond with *yes* or *no*.**")
                # Reset response to prompt again
                response = None
    
    # 9. No approval required, proceed to executor
    writer("\n\n✅ **No approval required. Proceeding to execution.**\n\n")
    return Command(
        update={
            "action_plan_history": action_plan_history,
            "action_plan_remaining": action_plan_remaining,
            "current_step_index": current_step_index,
            "current_step": current_step
        },
        goto="action_executor"
    )

# Function to run the action executor agent
async def run_action_executor_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Run the action executor agent to execute the current step in the action plan."""
    logger.info("Running action executor agent")    # Get the action plan and current step index from the state
    action_plan_remaining = state["action_plan_remaining"]
    action_executor_history = state.get("action_executor_history", [])
    device_facts = state["device_facts"]
    settings = state["settings"]
    test_data = state.get("test_data", {})
    
    # if not action_plan or current_step_index >= len(action_plan):
    #     logger.warning("No more steps to execute in the action plan")
    #     return state
    
    # Get the current step to execute
    current_step = state["current_step"]
    
    # Handle test mode - use command output from test data
    if settings.get("test_mode", False) and test_data:
        commands = current_step.commands
        # Get command output from test data or use default message
        #command_output = test_data.get("commands", {}).get(commands, "Output not available")
        
        # Create simulated result structure
        simulated_output = []
        for command in commands:
            command_output = test_data.get("commands", {}).get(command, "ERROR: Simulated command output missing from test data")
            simulated_output.append({"cmd": command, "output": command_output})

        description = current_step.description
        command_outputs = simulated_output
        errors = []
        execution_result = {
            "description": description,
            "command_outputs": command_outputs,
            "errors": errors
        }
    else:        # Access the global Netmiko connection
        global NETMIKO_CONNECTION
        
        # Create dependencies for the action executor
        deps = ActionExecutorDeps(
            current_step=current_step,
            device_driver=NETMIKO_CONNECTION,  # Pass actual Netmiko connection object
            device_facts=device_facts,
            settings=settings,
            logger=logger
        )
        
        # Run the action executor agent for the current step
        result = await run_action_executor(deps=deps)

        execution_result = result.output
        description = execution_result.description
        command_outputs = execution_result.command_outputs
        errors = execution_result.errors

    
    
    # Format the commands, their outputs, and errors with Markdown
    commands_md = ""
    for cmd in command_outputs:
        commands_md += f"- `{cmd['cmd']}`\n"    

    command_outputs_md = ""
    for output in command_outputs:
        command_outputs_md += f"```\n{output['output']}\n```\n"
    
    errors_md = ""
    if errors:
        for error in errors:
            errors_md += f"- ❌ **Error:** {error}\n"
    else:
        errors_md = "✅ **No errors encountered**"

    # Generate human-readable output for the writer with Markdown formatting
    mode_text = ""
    if settings.get("simulation_mode", True):
        mode_text = "**⚠️ SIMULATION MODE ⚠️**"
    elif settings.get("test_mode", False):
        mode_text = "**✅ TEST MODE**"
    else:
        mode_text = "**🔄 ACTUAL EXECUTION**"
        
    writer(f"""## 🔧 Executing Action

**Description:** 
{description}

**Commands:** 
{commands_md}

{mode_text}

### Output:
{command_outputs_md}

### Status: 
{errors_md}
""")

    action_executor_history.append(execution_result)
    
    # Update the state with the execution result
    return {
        **state,
        "execution_result": execution_result,
        "action_executor_history": action_executor_history
    }


# Function to run the action analyzer agent
async def run_action_analyzer_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Run the action analyzer agent to analyze the output of the executed step."""
    logger.info("Running action analyzer agent")
    
    # Get the necessary state data
    action_plan_history = state["action_plan_history"]
    action_plan_remaining = state["action_plan_remaining"]
    current_step_index = state["current_step_index"]
    current_step = state["current_step"]
    execution_result = state["execution_result"]
    fault_summary = state["fault_summary"]
    device_facts = state["device_facts"]
    settings = state["settings"]
    
    # Create dependencies for the action analyzer
    deps = ActionAnalyzerDependencies(
        action_plan_history=action_plan_history,
        action_plan_remaining=action_plan_remaining,
        current_step_index=current_step_index,
        current_step=current_step,
        execution_result=execution_result,
        fault_summary=fault_summary,
        device_facts=device_facts,
        settings=settings,
        logger=logger
    )
    
    # Run the action analyzer agent
    result = await run_action_analyzer(deps=deps)
    analysis_report = result.output
    
    # Format findings and analysis with Markdown
    analysis_md = analysis_report.analysis if analysis_report.analysis else "No analysis provided"
    
    findings_md = ""
    if analysis_report.findings:
        for finding in analysis_report.findings:
            findings_md += f"- {finding}\n"
    else:
        findings_md = "- No findings reported\n"
    
    next_action_type = analysis_report.next_action_type
    next_action_reason = analysis_report.next_action_reason
    
    # Generate human-readable output for the writer with Markdown formatting
    commands_text = "\n".join([f"- `{cmd}`" for cmd in current_step.commands]) if current_step.commands else "- No commands"
    writer(f"""## 📋 Analysis of Step {current_step_index+1} Results

**Commands Analyzed:**
{commands_text}

### 📊 Analysis:
{analysis_md}

### 🔍 Key Findings:
{findings_md}

### 🔄 Next Action:
- **Type:** {next_action_type}
- **Reason:** {next_action_reason}


""")    # Process updated action plan for both "new_action" or "continue" with variable population
    if analysis_report.updated_action_plan_remaining:
        action_plan_remaining = analysis_report.updated_action_plan_remaining
        # Generate human-readable output for the writer with Markdown formatting
        steps_markdown = []
        for i, step in enumerate(action_plan_remaining):
            # Format commands as a bulleted list
            commands_list = "\n".join([f"  - `{cmd}`" for cmd in step.commands]) if step.commands else "  - None"
            
            steps_markdown.append(f"""### Step {current_step_index+i+1}: {step.description}
- **🔄 Action Type:** {step.action_type}
- **📟 Commands:** 
{commands_list}
- **🔍 Expected Output:** {step.output_expectation}
- **⚠️ Requires Approval:** {'Yes' if step.requires_approval else 'No'}
""")        # Different messages based on action type
        if next_action_type == "new_action":
            writer(f"""## 🔍 Action Plan Has Been Updated Based Upon Findings

**Remaining Steps:** {len(action_plan_remaining)}

{''.join(steps_markdown)}
""")
        else:  # continue with variable population
            writer(f"""## 🔍 Variables Populated in Action Plan 

**Remaining Steps:** {len(action_plan_remaining)}

{''.join(steps_markdown)}
""")

    # Populate the analysis_report for the current step
    current_step.analysis_report = analysis_report

    # Update the state with the analysis report and latest action plan
    return {
        **state,
        "current_step": current_step,
        "action_plan_remaining": action_plan_remaining
    }

async def run_result_summary_node(state: NetworkTroubleshootingState, writer) -> NetworkTroubleshootingState:
    """Generate a summary of troubleshooting results."""
    logger.info("Running result summary node")
    
    # Close the Netmiko connection if it was opened
    global NETMIKO_CONNECTION
    if NETMIKO_CONNECTION:
        try:
            NETMIKO_CONNECTION.disconnect()
            logger.info("Closed Netmiko connection")
        except Exception as e:
            logger.error(f"Error closing Netmiko connection: {str(e)}")
            
    # Get the necessary state data
    fault_summary = state.get("fault_summary")
    action_plan_history = state.get("action_plan_history", [])
    action_plan_remaining = state.get("action_plan_remaining", [])
    current_step = state.get("current_step")
    current_step_index = state.get("current_step_index", 0)
    alert_raw_data = state.get("alert_raw_data", "")
    device_facts = state.get("device_facts", {})
    settings = state.get("settings", {})
    action_plan = state.get("action_plan", [])
    action_executor_history = state.get("action_executor_history", [])
    
    # Create dependencies for the result summary agent
    deps = ResultSummaryDependencies(
        fault_summary=fault_summary,
        action_plan_history=action_plan_history,
        action_plan_remaining=action_plan_remaining,
        current_step=current_step,
        current_step_index=current_step_index,
        alert_raw_data=alert_raw_data,
        device_facts=device_facts,
        settings=settings,
        logger=logger
    )
      # Run the result summary agent
    result = await run_result_summary(deps=deps)
    summary = result.output
    
    # Prepare numbered lists for key sections
    key_findings_list = "\n\n".join([f"**{i+1}.** {finding}" for i, finding in enumerate(summary.key_findings)])
    recommended_steps = "\n\n".join([f"**{i+1}.** {step}" for i, step in enumerate(summary.recommended_next_steps)])
    
    # Format successful and failed actions with appropriate icons
    successful_actions = "\n\n".join([f"✅ {action}" for action in summary.successful_actions]) if summary.successful_actions else "None"
    failed_actions = "\n\n".join([f"❌ {action}" for action in summary.failed_actions]) if summary.failed_actions else "None"
    
    # Determine resolution status emoji
    status_emoji = "✅" if summary.resolution_status.lower() == "resolved" else "⚠️" if "partial" in summary.resolution_status.lower() else "❌"
    
    # Generate human-readable output for the writer with enhanced Markdown formatting
    writer(f"""\n\n## 📋 Troubleshooting Results Summary

### 🔍 {summary.summary_title}

**Fault Recap:** {summary.fault_recap}  
**Resolution Status:** {status_emoji} {summary.resolution_status}

---

### 💡 Key Findings:
{key_findings_list}

---

### ✅ Successful Actions:
{successful_actions}

### ❌ Failed Actions:
{failed_actions}

---

### 🔎 Root Cause:
{summary.root_cause if summary.root_cause else "Not determined"}

---

### 📝 Recommended Next Steps:
{recommended_steps}

{f"---\n\n### ⚠️ Escalation Details:\n{summary.escalation_details}" if summary.escalation_details else ""}

---

### ⏱️ Execution Metrics:
```
Total Execution Time: {summary.time_metrics.get('total_execution_time', 'N/A')}
Steps Executed: {summary.time_metrics.get('steps_executed', 0)}
```
""")
    
    # Create a JSON payload with all required state data plus result summary
    results_payload = {
        "alert_raw_data": alert_raw_data,
        "fault_summary": fault_summary.model_dump() if fault_summary else None,
        "action_plan": [step.model_dump() for step in action_plan] if action_plan else [],
        "action_plan_history": [step.model_dump() for step in action_plan_history] if action_plan_history else [],
        "action_plan_remaining": [step.model_dump() for step in action_plan_remaining] if action_plan_remaining else [],
        "current_step_index": current_step_index,
        "current_step": current_step.model_dump() if current_step else None,
        "action_executor_history": action_executor_history,
        "device_facts": device_facts,
        "settings": {k: v for k, v in settings.items() if k != "logger"},  # Exclude non-serializable logger
        "result_summary": summary.model_dump()  # Add the result_summary output
    }    # Generate filename with current datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_filename = f"results_{timestamp}.json"
    workbench_path = Path("workbench")  # Using Path from pathlib for cross-platform compatibility
    static_path = Path("static")  # Path for static file serving
    
    try:
        # Ensure directories exist
        workbench_path.mkdir(exist_ok=True)
        static_path.mkdir(exist_ok=True)
        
        # Save the JSON payload to file in the workbench folder
        full_path = workbench_path / results_filename
        with open(full_path, 'w') as f:
            json.dump(results_payload, f, indent=2, default=str)  # Use default=str to handle any datetime objects
        
        # Save a copy to the static folder for direct URL access
        static_full_path = static_path / results_filename
        with open(static_full_path, 'w') as f:
            json.dump(results_payload, f, indent=2, default=str)
            
        logger.info(f"Results saved to {full_path} and {static_full_path}")
          # Add the URL link to the results file in the writer output
        writer(f"""
### 📊 Results JSON Data

The complete troubleshooting results are available as a JSON file.

**Direct link:** [results_{timestamp}.json](/app/static/{results_filename})

This file can be used for:
- Importing into data analysis tools
- Saving as part of incident documentation
- Processing with other automation systems

### 📋 Detailed Result Log

The complete troubleshooting session log is available for reference.

**Direct link:** [responses_{timestamp}.md](/app/static/responses_{timestamp}.md)

*This file contains the entire troubleshooting workflow and can be used for documentation or review purposes.*
""")
    except Exception as e:
        logger.error(f"Error saving results to file: {str(e)}")
    
    return {
        **state,
        # Reset the NetworkTroubleshootingState to its initial state for future executions
        "latest_user_message": None,
        "messages": [],
        "inventory": {},
        "alert_raw_data": None,
        "fault_summary": None,
        "action_plan": [],
        "action_plan_remaining": [],        
        "action_plan_history": [],
        "current_step_index": 0,
        "current_step": None,
        "action_executor_history": [],
        "execution_result": {},
        "analysis_report": None,
        "device_driver": None,
        "device_facts": {},
        "settings": {},
        "test_data": {}
    }

# # Function to check if we should continue with the next step or end the workflow
# def should_continue_or_end(state: NetworkTroubleshootingState, writer) -> str:
#     """Decide whether to continue with the next step or end the workflow."""
#     action_plan = state["action_plan"]
#     current_step_index = state["current_step_index"]
    
#     if not action_plan or current_step_index >= len(action_plan):
#         logger.info("No more steps to execute, ending workflow")
#         writer("No more steps to execute, ending workflow")
#         return "end"
#     else:
#         logger.info(f"Moving to next step: {current_step_index + 1}/{len(action_plan)}")
#         return "continue"

# Build and compile the graph
def build_graph() -> StateGraph:
    """Build and compile the network troubleshooting workflow graph."""
    # Create a new state graph
    builder = StateGraph(NetworkTroubleshootingState)
    
    # Add nodes for each agent
    builder.add_node("fault_summary_node", run_fault_summary_node)
    builder.add_node("init_deps", run_init_deps_node)
    builder.add_node("action_planner", run_action_planner_node)
    builder.add_node("action_router", run_action_router_node)
    builder.add_node("action_executor", run_action_executor_node)
    builder.add_node("action_analyzer", run_action_analyzer_node)
    builder.add_node("result_summary", run_result_summary_node)
    
    # Add edges to connect the nodes
    builder.add_edge(START, "fault_summary_node")
    builder.add_edge("fault_summary_node", "init_deps")
    builder.add_edge("init_deps", "action_planner")
    builder.add_edge("action_planner", "action_router")
    
    # Let action_router use Command objects for dynamic routing
    builder.add_edge("action_executor", "action_analyzer")
    builder.add_edge("action_analyzer", "action_router")
    builder.add_edge("result_summary", END)
    
    # Add conditional logic for looping or ending the workflow
    # builder.add_conditional_edges(
    #     "action_analyzer",
    #     should_continue_or_end,
    #     {
    #         "continue": "action_executor",
    #         "end": END
    #     }
    # )
    
    return builder

builder = build_graph()

# Configure persistence with memory saver
memory = MemorySaver()

# Compile the graph
agentic_flow = builder.compile(checkpointer=memory)
