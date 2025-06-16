import streamlit as st
import asyncio
import os
import glob
from pathlib import Path
from typing import Dict, List, Any
import yaml
from dotenv import load_dotenv
from httpx import AsyncClient
from datetime import datetime
import uuid
import logging
import subprocess
import sys
import time

from langgraph.types import Command

# Import the custom StreamlitLogger
from utils.streamlit_logger import get_streamlit_logger

# Import settings loader from graph.py
from graph import load_settings, settings_path

# Create a main logger for the streamlit app
logger = get_streamlit_logger("streamlit_app")

# Load environment variables from .env file
load_dotenv()

# Import agents from their respective packages
from agents.hello_world import run as run_hello_world
from agents.hello_world.agent import HelloWorldDependencies
from agents.fault_summary import run as run_fault_summary
from agents.fault_summary.agent import FaultSummaryDependencies
from agents.action_planner import run as run_action_planner
from agents.action_executor import run as run_action_executor
from agents.action_analyzer import run as run_action_analyzer
from agents.action_executor.agent import ActionExecutorDeps
from agents.action_planner.agent import ActionPlannerDependencies, TroubleshootingStep
from agents.fault_summary.agent import FaultSummary
from agents.action_analyzer.agent import ActionAnalyzerDependencies

# Import the graph for the Multi-Agent workflow
from graph import agentic_flow

# Function to save settings to YAML file
def save_settings(settings: Dict[str, Any], file_path: str = settings_path) -> bool:
    """Save current settings to the YAML file."""
    try:
        with open(file_path, 'w') as file:
            yaml.safe_dump(settings, file)
        logger.info(f"Settings saved to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {str(e)}")
        return False

# Get available test scenarios from the tests directory
def get_available_tests() -> List[str]:
    """Get a list of available test scenarios from tests folder."""
    test_files = glob.glob("tests/test_*.yml")
    test_names = []
    
    for test_file in test_files:
        # Extract test name from file path (test_name.yml -> name)
        test_name = os.path.basename(test_file).replace("test_", "").replace(".yml", "")
        test_names.append(test_name)
    
    return test_names

# Load test file preview to show in UI
def load_test_file_preview(test_name: str) -> str:
    """Load and return the contents of a test file for preview."""
    try:
        test_file = Path(f"tests/test_{test_name}.yml")
        if not test_file.exists():
            return "Test file not found"
        
        with open(test_file, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error loading test file: {e}"

# Set page configuration
st.set_page_config(
    page_title="ADAPT - Autonomous Network Troubleshooter",
    page_icon="🤖",
    layout="centered"
)


@st.cache_resource
def get_thread_id():
    return str(uuid.uuid4())

def cancel_workflow():
    """
    Cancel the active LangGraph workflow execution.
    
    This function:
    1. Resets the thread_id to generate a new one for future runs
    2. Sets workflow_active flag to False
    3. Reruns the Streamlit app to refresh UI state
    
    Since LangGraph threads are stateful and persist between runs,
    generating a new thread_id effectively "cancels" the current execution
    by ensuring future interactions won't continue the canceled workflow.
    """
    global thread_id
    logger.info(f"Cancelling active workflow with thread_id: {thread_id}")
    thread_id = reset_thread_id()
    st.session_state.workflow_active = False
    st.rerun()

# Add a function to reset the thread_id cache when needed
def reset_thread_id():
    get_thread_id.clear()
    return get_thread_id()

thread_id = get_thread_id()

async def run_agent_with_streaming(user_input: str, settings: Dict[str, bool] = None):
    """
    Run the agent with streaming text for the user_input prompt,
    while maintaining the entire conversation in `st.session_state.messages`.
    
    If step_mode is enabled, the LangGraph execution will pause between nodes
    and wait for user input before proceeding.
    """
    if settings is None:
        settings = {"simulation_mode": True, "debug_mode": False}
        
    config = {
        "configurable": {
            "thread_id": thread_id
        },
        "recursion_limit": 50
    }

    # Set the workflow_active flag to True
    st.session_state.workflow_active = True

    # Initialize node_output to store the output from each node when in step mode
    node_output = ""
    step_mode = settings.get("step_mode", False)

    # First message from user
    if len(st.session_state.messages) == 1:
        stream_iterator = agentic_flow.astream(
            {"latest_user_message": user_input, "settings": settings}, 
            config, 
            stream_mode="custom"
        )
        
        if step_mode:
            # In step mode, process one node at a time and pause for user input
            try:
                # Get the first node's output
                node_output = await stream_iterator.__anext__()
                yield f"{node_output}\n\n---\n\n⏸️ **Step Mode**: Paused after node execution. Enter anything to continue to the next step."
                
                # Wait for user input in the main loop (handled externally)
                # When user provides input, this function will be called again with Command(resume=input)
            except StopAsyncIteration:
                # End of stream reached
                pass
        else:
            # Normal mode, stream all nodes without pausing
            async for msg in stream_iterator:
                yield msg
    # Continue the conversation
    else:
        stream_iterator = agentic_flow.astream(
            Command(resume=user_input), 
            config, 
            stream_mode="custom"
        )
        
        if step_mode:
            try:
                # Get the next node's output after user provides input to continue
                node_output = await stream_iterator.__anext__()
                yield f"{node_output}\n\n---\n\n⏸️ **Step Mode**: Paused after node execution. Enter anything to continue to the next step."
            except StopAsyncIteration:
                # End of stream reached
                yield "✅ **Workflow Complete**: All nodes have been executed."
        else:
            async for msg in stream_iterator:
                yield msg

# Initialize settings in session state if it doesn't exist
if "settings" not in st.session_state:
    # Load settings from the configuration file
    config_settings = load_settings(settings_path)
    st.session_state.settings = config_settings
else:
    # If settings are already in session state, ensure all required settings are present
    config_settings = load_settings(settings_path)
    for key, value in config_settings.items():
        if key not in st.session_state.settings:
            st.session_state.settings[key] = value

# Initialize workflow_active flag if it doesn't exist
if "workflow_active" not in st.session_state:
    st.session_state.workflow_active = False

# Add a title and description
st.title("🤖 ADAPT - Autonomous Network Troubleshooter")

# Track Alert Queue process info in session state
if 'alert_queue_process' not in st.session_state:
    st.session_state.alert_queue_process = None
if 'alert_queue_pid' not in st.session_state:
    st.session_state.alert_queue_pid = None
if 'alert_queue_port' not in st.session_state:
    st.session_state.alert_queue_port = 8001

# Add sidebar for agent selection
with st.sidebar:
    st.header("Select Workflow")
    agent_type = st.selectbox(
        "Choose a workflow option:",
        options=[
            "Full Multi-Agent Workflow",
            "Fault Summarizer Agent",
            "Hello World Agent"
        ],
        index=0,
        help="Select the agent or workflow you want to run. Most agents are currently unavailable for execution in standalone mode.")
    
    # Determine if controls should be disabled (when not using Full Multi-Agent Workflow)
    disable_controls = agent_type != "Full Multi-Agent Workflow"
    
    # Add toggles for settings
    st.header("Settings")
    simulation_mode = st.toggle("Simulation Mode", value=st.session_state.settings["simulation_mode"], disabled=disable_controls, help="Enable simulation mode to run commands without actual execution")
    debug_mode = st.toggle("Debug Mode", value=st.session_state.settings["debug_mode"], disabled=True, help="Enable debug mode for additional logging and information")

    # Test mode toggle and test scenario selection
    test_mode = st.toggle("Test Mode", value=st.session_state.settings["test_mode"], 
                disabled=disable_controls,
                help="Enable test mode to use predefined test data instead of real executions")
    
    # If test mode is enabled, show test scenario selection
    if test_mode:
        available_tests = get_available_tests()
        
        if available_tests:
            test_name = st.selectbox(
                "Select Test Scenario",
                options=available_tests,
                index=None,
                placeholder="Choose a test scenario...",
                help="Select a predefined test scenario to run",
                key="test_scenario_select",
                disabled=disable_controls
            )
            
            # Initialize with the saved value if available
            if not test_name and st.session_state.settings["test_name"]:
                if st.session_state.settings["test_name"] in available_tests:
                    test_name = st.session_state.settings["test_name"]
            
            # Add Run Test button if a test scenario is selected
            if test_name:
                run_test_button = st.button("Run Test", key="run_test_button", help="Run the selected test scenario", disabled=disable_controls)
                if run_test_button:
                    st.session_state.settings["test_name"] = test_name
                    st.session_state.test_user_input = f"Run test scenario: {test_name}"
                    st.session_state.messages = []
                    # Reset the thread_id to make sure we get rid of any stale state data for the graph
                    thread_id = reset_thread_id()
                    st.rerun()
            
            # # Show test file preview
            # with st.expander("Test Scenario Preview"):
            #     st.code(load_test_file_preview(test_name), language="yaml")
        else:
            st.warning("No test scenarios found. Create YAML files in the tests/ directory with the format test_name.yml")
            test_name = ""
            
    else:
        test_name = ""
    
    # Add number input for max_steps
    max_steps = st.number_input(
        "Max Steps", 
        min_value=1,
        max_value=25,
        value=st.session_state.settings["max_steps"],
        step=1,
        disabled=disable_controls,
        help="Maximum number of steps to execute before escalating to human intervention"
    )
    
    # Add toggle for adaptive_mode
    adaptive_mode = st.toggle(
        "Adaptive Mode", 
        value=st.session_state.settings.get("adaptive_mode", True),
        disabled=disable_controls,
        help="When enabled, allows the Action Analyzer to recommend new troubleshooting steps based on analysis"
    )
    
    # Add toggle for step_mode
    step_mode = st.toggle(
        "Step Mode",
        value=st.session_state.settings.get("step_mode", False),
        disabled=disable_controls,
        help="When enabled, pauses between execution of each node in the workflow and waits for user input before proceeding"
    )

    # Golden Rules section with popover
    with st.popover("Golden Rules", disabled=disable_controls):
        st.caption("These rules are always followed by the agentic workflow:")
        
        # Initialize golden_rules if not already in session_state.settings
        if "golden_rules" not in st.session_state.settings:
            st.session_state.settings["golden_rules"] = []
        
        # Display current golden rules with the option to remove them
        for i, rule in enumerate(st.session_state.settings["golden_rules"]):
            col1, col2 = st.columns([5, 1])
            with col1:
                rule_text = st.text_input(f"Rule {i+1}", value=rule, key=f"rule_{i}", disabled=disable_controls)
                # Update rule text if changed
                if rule_text != rule:
                    st.session_state.settings["golden_rules"][i] = rule_text
            
            with col2:
                if st.button("🗑️", key=f"delete_rule_{i}", disabled=disable_controls):
                    st.session_state.settings["golden_rules"].pop(i)
                    st.rerun()
        
        # Add new rule
        new_rule = st.text_input("Add new rule", key="new_rule_input", disabled=disable_controls)
        if st.button("Add Rule", key="add_rule_btn", disabled=disable_controls):
            if new_rule.strip():
                st.session_state.settings["golden_rules"].append(new_rule)
                st.rerun()
    
    # Custom Instructions section with popover
    with st.popover("Custom Instructions", disabled=disable_controls):
        st.caption("Add any custom instructions for the agentic workflow:")
        # Initialize custom_instructions in settings if not already present
        if "custom_instructions" not in st.session_state.settings:
            st.session_state.settings["custom_instructions"] = ""
        custom_instructions = st.text_area(
            "Custom Instructions",
            value=st.session_state.settings["custom_instructions"],
            key="custom_instructions_input",
            height=100,
            disabled=disable_controls,
            help="Provide any custom instructions or context for the workflow."
        )
        if custom_instructions != st.session_state.settings["custom_instructions"]:
            st.session_state.settings["custom_instructions"] = custom_instructions
    
    # Persist settings and reset buttons on the same line
    col_save, col_reset = st.columns([1, 1])
    with col_save:
        if st.button("Save Settings", disabled=disable_controls):
            success = save_settings(st.session_state.settings)
            if success:
                st.success("Settings saved successfully!")
            else:
                st.error("Failed to save settings.")
    with col_reset:
        if st.button("Default Settings", disabled=disable_controls):
            config_settings = load_settings(settings_path)
            st.session_state.settings = config_settings
            st.rerun()
    # Update session state with current settings (do not remove this section)
    st.session_state.settings["simulation_mode"] = simulation_mode and not test_mode
    st.session_state.settings["debug_mode"] = debug_mode
    st.session_state.settings["adaptive_mode"] = adaptive_mode
    st.session_state.settings["step_mode"] = step_mode
    st.session_state.settings["test_mode"] = test_mode
    st.session_state.settings["test_name"] = test_name
    st.session_state.settings["max_steps"] = max_steps
    
    st.divider()

    if st.button("Reset Chat History", key="clear_chat"):  # This button shouldn't be disabled
        st.session_state.messages = []
        thread_id = reset_thread_id()
        st.session_state.workflow_active = False
        st.rerun()

# --- Alert Queue Control Button ---
    alert_queue_port = st.number_input(
        "Alert Queue Port",
        min_value=1024,
        max_value=65535,
        value=st.session_state.get("alert_queue_port", 8001),
        step=1,
        disabled=disable_controls,
        help="Port to run the Alert Queue service on (default: 8001)"
    )
    st.session_state["alert_queue_port"] = alert_queue_port

    alert_queue_running = st.session_state.alert_queue_process is not None and st.session_state.alert_queue_process.poll() is None
    if alert_queue_running:
        if st.button("🛑 Stop Alert Queue", key="stop_alert_queue_btn", disabled=disable_controls):
            try:
                st.session_state.alert_queue_process.terminate()
                st.session_state.alert_queue_process.wait(timeout=5)
            except Exception as e:
                st.error(f"Failed to stop Alert Queue: {e}")
            st.session_state.alert_queue_process = None
            st.session_state.alert_queue_pid = None
            st.success("Alert Queue stopped.")
            time.sleep(5)
            st.rerun()
        alert_queue_doc_url = f"http://localhost:{alert_queue_port}/docs"
        st.caption(f"Alert Queue Docs: {alert_queue_doc_url}")
    else:
        if st.button("▶️ Start Alert Queue", key="start_alert_queue_btn", disabled=disable_controls):
            try:
                alert_queue_process = subprocess.Popen([
                    sys.executable, "alert_queue.py", "--port", str(alert_queue_port)
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                st.session_state.alert_queue_process = alert_queue_process
                st.session_state.alert_queue_pid = alert_queue_process.pid
                st.success(f"Alert Queue started (PID: {alert_queue_process.pid}) on port {alert_queue_port}")
                time.sleep(5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to start Alert Queue: {e}")
    if st.session_state.alert_queue_pid:
        st.caption(f"Alert Queue Port: {st.session_state.alert_queue_port}\n(Process ID: {st.session_state.alert_queue_pid})")
    st.divider()
    # --- End Alert Queue Control Button ---
    

# Display appropriate header and description based on selected agent
if agent_type == "Hello World Agent":
    st.markdown("### 👋 Hello World Agent")
    st.markdown("This is a simple hello-world agent for validating LLM connectivity. It always responds to the user with 'Hello, world!'")
elif agent_type == "Fault Summarizer Agent":
    st.markdown("### 🔧 Fault Summarizer")
    st.markdown("Describe a network fault, and this agent will analyze and summarize the issue.")
elif agent_type == "Action Planner Agent":
    st.markdown("### 🔍 Network Troubleshooting Planner")
    st.markdown("Provide a summary of a network fault, and this agent will create a detailed troubleshooting plan with specific commands to execute.")
elif agent_type == "Action Analyzer Agent":
    st.markdown("### 📊 Action Analyzer")
    st.markdown("This agent analyzes the output of network commands and provides structured insights, findings, and recommendations.")
    st.info("Enter a network command output to analyze, or paste the full output of a previous command execution.")
elif agent_type == "Full Multi-Agent Workflow":
    st.markdown("### 🔄 Multi-Agent Network Troubleshooting System")
    st.markdown("ADAPT is an autonomous troubleshooting system that adjusts its actions based on real-time findings.")
    st.markdown("Describe a network fault or send a network alert, and the workflow will run through these steps:")
    st.markdown("1. 🔧 **Fault Summary**: Analyze and summarize the issue")
    st.markdown("2. 🔍 **Action Planning**: Create a troubleshooting plan with specific steps towards diagnosing and resolving the issue")
    st.markdown("3. 🖥️ **Action Execution**: Execute each step of the plan, interacting with live network devices")
    st.markdown("4. 🧠 **Action Analysis**: Analyze the output of each step and decide what's next")
    st.markdown("5. 📊 **Result Summary**: Provide a comprehensive report of actions taken, findings, and recommendations")
    if st.session_state.settings["test_mode"]:
        st.info(f"Running in TEST MODE with scenario: {test_name or 'None selected'}")
    elif st.session_state.settings["simulation_mode"]:
        st.info("Running in SIMULATION MODE")
    else:
        st.warning("Running in PRODUCTION MODE - Commands will execute on real devices")
      # Show step mode warning if enabled
    if st.session_state.settings.get("step_mode", False):
        st.info("🔄 Running in STEP MODE: Execution will pause between workflow steps and wait for user input")
    
    # Show golden rules information
    with st.expander("Active Golden Rules"):
        if st.session_state.settings.get("golden_rules"):
            for i, rule in enumerate(st.session_state.settings["golden_rules"]):
                st.markdown(f"{i+1}. {rule}")
        else:
            st.markdown("No golden rules configured")

else:
    st.markdown("### 🖥️ Command Executor")
    st.markdown("Enter a network command to execute on a device. The agent will determine if it's an operational or configuration command and execute it appropriately.")
    st.info("Currently running in: " + ("SIMULATION mode" if st.session_state.settings["simulation_mode"] else "REAL EXECUTION mode via SSH"))

# Initialize chat history in session state if it doesn't exist
if "messages" not in st.session_state:
    st.session_state.messages = []

# Reset chat when changing agents
if "current_agent" not in st.session_state or st.session_state.current_agent != agent_type:
    st.session_state.messages = []
    st.session_state.current_agent = agent_type

# Initialize current_response for debug logging
if "current_response" not in st.session_state:
    st.session_state.current_response = None

# Initialize test_user_input if it doesn't exist
if "test_user_input" not in st.session_state:
    st.session_state.test_user_input = None

# Add Alert Queue Check button and logic
alert_queue_file = os.path.join(os.path.dirname(__file__), 'workbench', 'alert_queue.txt')
if 'alert_queue_user_input' not in st.session_state:
    st.session_state.alert_queue_user_input = None

def dequeue_oldest_alert(alert_queue_file):
    """
    Reads and removes the oldest alert (first line) from the alert queue file (JSON Lines format).
    Returns the alert content as a pretty-printed string, or None if the queue is empty.
    """
    import json
    import threading
    lock = threading.Lock()
    with lock:
        if not os.path.exists(alert_queue_file):
            return None
        with open(alert_queue_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        if not lines:
            return None
        oldest_alert_json = lines[0]
        remaining = lines[1:]
        with open(alert_queue_file, 'w', encoding='utf-8') as f:
            f.writelines(remaining)
        try:
            alert_obj = json.loads(oldest_alert_json)
            # Pretty print the JSON object
            return json.dumps(alert_obj, indent=4, ensure_ascii=False)
        except Exception:
            return oldest_alert_json.strip()

# Check if we're in Full Multi-Agent Workflow mode to enable/disable the button
if st.button('Check Alert Queue', key='check_alert_queue', disabled=agent_type != "Full Multi-Agent Workflow"):
    alert_content = dequeue_oldest_alert(alert_queue_file)
    if alert_content:
        st.session_state.alert_queue_user_input = alert_content
        st.success('Dequeued one alert from the queue.')
    else:
        st.info('No alerts in the queue.')

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User input
user_input = st.chat_input("Say something to the agent...")
if st.session_state.test_user_input:
    user_input = st.session_state.test_user_input
    st.session_state.test_user_input = None  # Clear the test input after using it
elif st.session_state.alert_queue_user_input:
    user_input = st.session_state.alert_queue_user_input
    st.session_state.messages = []
    # Reset the thread_id to make sure we get rid of any stale state data for the graph
    thread_id = reset_thread_id()
    st.session_state.alert_queue_user_input = None  # Clear the alert queue input after using it

# Handle user input
if user_input:
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Check if we're cancelling an active workflow via a special command
    if user_input.strip().lower() in ["cancel", "stop", "abort", "halt"] and st.session_state.workflow_active:
        cancel_workflow()
        with st.chat_message("assistant"):
            st.markdown("⚠️ Workflow cancelled as requested. You can start a new conversation.")
        st.stop()  # Stop further execution of this run
    
    # Display assistant response with a spinner
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        with st.spinner("Thinking..."):
            # Get response from the appropriate agent
            async def get_response():
                # Create a logger specific to the current agent
                agent_logger = get_streamlit_logger(f"agent.{agent_type.replace(' ', '_').lower()}")
                
                # Initialize empty response for debug messages to append to
                st.session_state.current_response = ""
                
                if st.session_state.settings["debug_mode"]:
                    logger.info(f"Processing input with {agent_type}", extra={"user_input": user_input})
                
                if agent_type == "Hello World Agent":
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Hello World Agent", extra={"user_input": user_input})
                    
                    # Create dependencies for the Hello World agent
                    hello_world_deps = HelloWorldDependencies(
                        settings=st.session_state.settings,
                        logger=agent_logger
                    )
                    
                    # Pass the dependencies to the agent
                    result = await run_hello_world(user_input, deps=hello_world_deps)
                    return result.output
                elif agent_type == "Full Multi-Agent Workflow":
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Multi-Agent Workflow", extra={"user_input": user_input})
                    response_content = ""
                    async for chunk in run_agent_with_streaming(user_input, settings=st.session_state.settings):
                        response_content += chunk
                        # Update the placeholder with the current response content
                        message_placeholder.markdown(response_content)

                    # Generate filename with timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    response_filename = f"responses_{timestamp}.md"
                    
                    # Save to workbench directory
                    workbench_path = os.path.join("workbench", response_filename)
                    os.makedirs("workbench", exist_ok=True)
                    with open(workbench_path, "w", encoding="utf-8") as f:
                        f.write(response_content)
                    
                    # Save to static directory for direct URL access
                    static_path = os.path.join("static", response_filename)
                    os.makedirs("static", exist_ok=True)
                    with open(static_path, "w", encoding="utf-8") as f:
                        f.write(response_content)
                        
                    return response_content
                    
                elif agent_type == "Fault Summarizer Agent":
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Fault Summarizer Agent", extra={"user_input": user_input})
                    
                    # Create dependencies for the Fault Summarizer agent
                    fault_summary_deps = FaultSummaryDependencies(
                        settings=st.session_state.settings,
                        logger=agent_logger
                    )
                    
                    # Pass dependencies to the agent
                    result = await run_fault_summary(user_input, deps=fault_summary_deps)
                    # Format structured output for display
                    fault_summary = result.output
                    fault_summary = result.output

                    # Generate output showing the raw alert that was received and display fault summary
                    formatted_output = f"""## 🚨 Alert Received

The following alert has been received:
```
{user_input}
```

## 📊 Fault Summary

**Title:** {fault_summary.title}  
**Summary:** {fault_summary.summary}  
**Device:** {fault_summary.hostname}  
**Severity:** {fault_summary.severity}  
**Timestamp:** {fault_summary.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  
**Additional Metadata:** {fault_summary.metadata}
"""
                    return formatted_output
                elif agent_type == "Action Planner Agent":
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Network Troubleshooting Planner Agent", extra={"user_input": user_input})
                    
                    # Create a new FaultSummary with the user input as the summary
                    # THIS IS ONLY TEMPORARY until we introduce LangGraph
                    # TODO: Update prompt for Action Planner to support plain text user input for standalone execution
                    network_fault_summary = FaultSummary(
                        summary=user_input,
                        metadata={"source": "user_input", "raw_text": user_input}
                    )
                    
                    # Create the dependency object
                    action_planner_deps = ActionPlannerDependencies(
                        fault_summary=network_fault_summary,
                        settings=st.session_state.settings,
                        logger=agent_logger
                    )
                    
                    # Call the action planner with the dependencies
                    result = await run_action_planner(user_input, deps=action_planner_deps)
                    action_plan = result.output
                    
                    # Format the troubleshooting steps for display
                    formatted_output = "### Network Troubleshooting Plan\n\n"
                    
                    for i, step in enumerate(action_plan, 1):
                        approval_tag = "⚠️ **Requires Approval**" if step.requires_approval else "✅ **Safe to Execute**"
                        formatted_output += f"## Step {i}: {step.description}\n\n"
                        formatted_output += f"{approval_tag}\n\n"
                        formatted_output += f"**Commands:**\n```\n"
                        if step.commands:
                            formatted_output += "\n".join(step.commands)
                        formatted_output += "\n```\n\n"
                        formatted_output += f"**Expected Output:**\n{step.output_expectation}\n\n"
                        formatted_output += "---\n\n"
                    
                    return formatted_output
                elif agent_type == "Action Analyzer Agent":
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Action Analyzer Agent", extra={"user_input": user_input})
                    
                    # For demonstration purposes, use a sample output and dependencies
                    # In a real workflow, these would come from previous steps in the troubleshooting process
                    
                    # Create a simulated command output for the action executor
                    command_output = {
                        "cmd": user_input.splitlines()[0],  # Use the first line of user input as the command
                        "output": user_input  # Use the user input as the command output to analyze
                    }
                    
                    # Create sample dependencies for the analyzer
                    # TODO: Update Action Angalyzer to support plain text user input for standalone execution
                    network_fault_summary = FaultSummary(
                        title="Network Interface Analysis",
                        summary="Analyzing network interface performance and errors",
                        hostname="router1.example.com",
                        severity="Medium",
                        timestamp=datetime.now().isoformat(),
                        metadata={"source": "user_input", "raw_text": "Interface analysis"}
                    )
                    
                    action = TroubleshootingStep(
                        description="Analyze interface statistics",
                        action_type="diagnostic",
                        commands=["show interfaces"],
                        output_expectation="Review for errors, bandwidth utilization, and packet loss",
                        requires_approval=False
                    )
                    
                    executor_output = type('ActionExecutorOutput', (), {
                        'command_outputs': [command_output],
                        'simulation_mode': True,
                        'errors': None
                    })
                    
                    # Create the dependency object for the analyzer
                    action_analyzer_deps = ActionAnalyzerDependencies(
                        executor_output=executor_output,
                        action_plan=[action],
                        fault_summary=network_fault_summary,
                        current_step=action,
                        settings=st.session_state.settings,
                        logger=agent_logger
                    )
                    
                    # Call the action analyzer with dependencies
                    result = await run_action_analyzer(deps=action_analyzer_deps)
                    analysis_report = result.output
                    
                    # Format the analysis report for display
                    formatted_output = """### Network Command Output Analysis\n\n"""
                    
                    # Key Findings section
                    formatted_output += "#### 📊 Key Findings\n"
                    for finding in analysis_report.key_findings:
                        formatted_output += f"- {finding}\n"
                    
                    # Issues section
                    formatted_output += "\n#### ⚠️ Issues Identified\n"
                    if analysis_report.issues_identified:
                        for issue in analysis_report.issues_identified:
                            formatted_output += f"- {issue}\n"
                    else:
                        formatted_output += "- No issues identified\n"
                    
                    # Recommendations section
                    formatted_output += "\n#### 📋 Recommendations\n"
                    for recommendation in analysis_report.recommendations:
                        formatted_output += f"- {recommendation}\n"
                    
                    # Confidence level
                    formatted_output += f"\n**Confidence Level:** {analysis_report.confidence_level}\n"
                    
                    return formatted_output
                else:  # Command Executor
                    if st.session_state.settings["debug_mode"]:
                        agent_logger.info("Running Command Executor Agent", extra={"user_input": user_input})
                    
                    action = TroubleshootingStep(
                        description="Execute CLI command",
                        action_type="diagnostic",
                        commands=[user_input],
                        output_expectation="Command should execute successfully",
                        requires_approval=False
                    )

                    # Create dependencies for the action executor
                    action_executor_deps = ActionExecutorDeps(
                        current_step=action,
                        simulation_mode=st.session_state.settings["simulation_mode"],
                        settings=st.session_state.settings,
                        logger=agent_logger
                    )
                    
                    # Execute the commands using the action_executor agent
                    result = await run_action_executor(deps=action_executor_deps)
                    
                    result_command_outputs = getattr(result.output,"command_outputs", [{"cmd": "No output", "output": "No output"}])
                    result_simulation_mode = getattr(result.output,"simulation_mode", True)
                    result_errors = getattr(result.output,"errors", [])
                    
                    # Format the output for display based on the updated ActionExecutorOutput structure
                    formatted_output = f"""
### Command Execution Result

**Simulation Mode:** {"Yes" if result_simulation_mode else "No"}

**Command Outputs:**
"""
                    
                    for cmd_output in result_command_outputs:
                        formatted_output += f"""
**Command:** `{cmd_output['cmd']}`

```
{cmd_output['output']}
```
"""
                    
                    if result_errors and len(result_errors) > 0:
                        formatted_output += "\n**Errors:**\n"
                        for error in result_errors:
                            formatted_output += f"- {error}\n"
                    
                    return formatted_output
            
            response = asyncio.run(get_response())
            # Print out the response to chat interface
            if agent_type != "Full Multi-Agent Workflow":
                # For non-workflow agents, just display the response directly
                message_placeholder.markdown(response)
            
            # Reset the current response accumulator
            st.session_state.current_response = None
    
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})
