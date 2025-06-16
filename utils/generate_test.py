#!/usr/bin/env python
"""
Test Generator Module

This module provides functionality to generate network troubleshooting test files using PydanticAI.
The generated test files contain structured data for network fault alerts, custom instructions
for troubleshooting, and simulated command output for network devices.

Usage:
    python -m utils.generate_test

The module will prompt for input describing the type of network fault to simulate,
and will generate                     edit_result = await test_generator_agent.run(
                        f"The user wants to modify the current network troubleshooting test. Their instructions are:\n\n"
                        f"{edit_prompt}\n\n"
                        f"Make the requested changes to the test and return the complete updated test JSON "
                        f"that includes all necessary components (alert_payload, custom_instructions, expected_rca, commands, and device_facts).",
                        deps=deps,
                        message_history=message_history
                    )est file in the tests/ directory.
"""

import os
import yaml
import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Any
from pathlib import Path
import re
import textwrap

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class TestGeneratorDeps(BaseModel):
    """Dependencies for the test generator agent."""
    debug_mode: bool = False


class NetworkCommand(BaseModel):
    """Representation of a network command and its simulated output."""
    command: str = Field(..., description="The CLI command to execute")
    output: str = Field(..., description="The simulated output of the command")


class TestJSON(BaseModel):
    """Structure of the test JSON file to be generated."""
    alert_payload: str = Field(..., description="JSON string containing the alert payload")
    custom_instructions: str = Field(..., description="Custom instructions for diagnosing and fixing the network fault")
    expected_rca: str = Field(..., description="Expected root cause analysis for the network fault")
    commands: Dict[str, str] = Field(default_factory=dict, description="Dictionary mapping commands to their simulated outputs")
    device_facts: Dict[str, Any] = Field(default_factory=dict, description="Dictionary containing device facts like hostname, OS version, model, and interfaces")


class TestSpec(BaseModel):
    """User-provided specification for the test to generate."""
    test_name: str = Field(..., description="Name of the test (will be used in filename)")
    alert_type: str = Field(..., description="Type of network alert (e.g., BGP flap, interface down)")
    device_type: str = Field(..., description="Type of network device (e.g., router, switch)")
    description: str = Field(..., description="Detailed description of the network issue")
    root_cause: Optional[str] = Field(None, description="The root cause of the network issue (if known)")
    raw_event: Optional[str] = Field(None, description="Raw event details such as a syslog message associated with the fault")


SYSTEM_PROMPT = """
You are a **Network Test Generator Agent** tasked with creating realistic test scenarios for an AI-driven network troubleshooting system.

Your job is to generate a **single, complete JSON document** that simulates a network fault scenario and provides data for testing automated troubleshooting workflows.
You will follow the following process:
1. Generate a JSON document with test data
2. Reflect on the quality and completeness of that data
3. If needed, revise and return an improved version

The document MUST contain the following four top-level fields:

---

## 1. `alert_payload` (object)
A structured representation of a network alert. It MUST include:
- `alert_id` (string): A unique ID in the format TYPE-XXXX
- `device` (string): Hostname of the affected device
- `timestamp` (string): Current time in ISO-8601 format
- `severity` (string): One of: "critical", "high", "medium", or "low"
- `message` (string): A one-line summary of the issue
- `raw_event` (string): Raw syslog or event message that triggered the alert

---

## 2. `custom_instructions` (string, markdown format)

This section contains **step-by-step troubleshooting and remediation guidance**. It should be written to help a network engineer determine the root cause (which is unknown to the user, even if `expected_rca` is already known to you) and, if possible, fix the issue.
Each step in the remediation guide should explain what to look for and then what to do next based upon the potential findings.

🧠 Think like a trainer: include steps that explore **multiple potential causes** for the alert, not just the one you will list in the RCA.

Use the following format:

```

Objective: <Briefly explain the purpose of the steps below>

General Instructions:
<Any best practices, safety notes, or relevant context>

Remediation Guide:

1. Step to diagnose and/or resolve the issue along with what to look for to indicate root cause and what to do next based upon potential findings.
2. Step to diagnose and/or resolve the issue
3. ...

...

```

- Number the steps (no more than 15 total)
- When relevant, mention CLI commands in each actionable step
- For each CLI command listed, the `commands` section MUST include corresponding simulated output

---

## 3. `expected_rca` (string)

A detailed technical explanation of the most likely root cause, including:
- A concise description of the fault
- Supporting evidence from CLI command outputs
- How a network engineer would interpret the data

---

## 4. `commands` (object)

⚠️ **MANDATORY SECTION**

This is a dictionary where:
- **Each key is a CLI command** mentioned in the remediation guide
- **Each value is a multiline string** simulating output from that command

The simulated output must:
- Match the syntax and format of real device CLI (e.g. Cisco IOS, IOS XR, NX-OS)
- Contain realistic values and artifacts (e.g. logs, counters, state)
- Support the root cause shown in `expected_rca`

✅ **You MUST include every command referenced in the remediation guide**
❌ Do not invent commands in this section that weren't in the steps
✅ Format each value as a properly escaped JSON string using `\n` for line breaks

---

## 5. `device_facts` (object)

This section contains device information that would normally be collected during device connectivity. It MUST include:

- `reachable` (boolean): Whether the device is reachable (typically true)
- `hostname` (string): The hostname of the device (should match the device in alert_payload)
- `vendor` (string): The vendor name (e.g., cisco, juniper)
- `model` (string): The device model (e.g., CSR1000v, ASR9000, etc.)
- `os` (string): The operating system (e.g., ios, iosxr, nxos, junos)
- `os_version` (string): The OS version (e.g., 16.9.3, 7.3.2)
- `interface_list` (array): List of interfaces on the device
- `fqdn` (string): Fully qualified domain name (e.g., router1.example.com)
- `serial_number` (string): The device serial number
- `uptime` (number): Device uptime in seconds
- `errors` (array): List of errors (empty array if no errors)

## OUTPUT FORMAT

Return a single JSON object with the following top-level keys:
- `alert_payload` (object)
- `custom_instructions` (string)
- `expected_rca` (string)
- `commands` (object)
- `device_facts` (object)

Ensure it is:
- Fully escaped, valid JSON
- Cohesive and consistent across all sections

---

## WORKFLOW

1. Choose a realistic network fault scenario (e.g., interface errors, BGP session loss, OSPF adjacency issues)
2. Create an alert payload that accurately reflects the condition
3. Write `custom_instructions` with diagnostic and remediation steps that lead towards the root cause and remediation
4. Generate realistic simulated output for every CLI command
5. Provide a clear RCA that explains how the evidence points to the true cause
6. Create `device_facts` that are consistent with the device in the alert payload and command outputs

**Do not skip the `commands` section.**  
**Do not leave any command without an output.**  
**Ensure `device_facts` has all required fields and is consistent with the scenario.**
**Return a complete and valid JSON object.**

---

## REFLECTION

After generating the JSON, evaluate your own output by answering:

1. Does `commands` include every CLI command referenced in the `custom_instructions`?
2. Is the command output realistic and consistent with the fault?
3. Does the `expected_rca` cite evidence that actually appears in the command output?
4. Are any fields incomplete, redundant, or inconsistent?
5. Is the command output consistent across all commands to indicate that they were all retrieved from the same device? For example, does the same field or counter show the same value in multiple commands?
6. Does `device_facts` contain all required fields and are they consistent with the scenario?
7. Do the hostname and device information in `device_facts` match those in the `alert_payload`?

If the answer to any of these is "no", revise the JSON output accordingly.

```

"""


# Initialize the test generator agent
test_generator_agent = Agent(
    model='openai:o4-mini',
    system_prompt=SYSTEM_PROMPT,
    output_type=TestJSON,
    retries=2,
    instrument=True,
    message_history=None  # Will be populated during interactive sessions
)


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be used as a safe filename.
    
    Args:
        name: The input string to sanitize
        
    Returns:
        A sanitized string suitable for use as a filename
    """
    # Replace spaces and special characters with underscores
    sanitized = re.sub(r'[^\w\s-]', '_', name.lower())
    # Replace spaces with underscores
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized


async def generate_test_file(spec: TestSpec) -> Path:
    """
    Generate a test YAML file based on the provided specification.
    
    Args:
        spec: TestSpec object containing the test specifications
        
    Returns:
        Path: The path to the generated test file
    """
    # Create prompt from test specification
    prompt = f"""
Generate a complete test JSON file for a network troubleshooting scenario based upon the following details:

- Test Name: {spec.test_name}
- Alert Type: {spec.alert_type}
- Device Type: {spec.device_type}
- Fault Description: {spec.description}

"""

    # Create dependencies
    deps = TestGeneratorDeps(debug_mode=False)
    
    print(f"Generating test file for '{spec.test_name}'...")
    print("This may take a moment...")
    
    # Run the test generator agent
    result = await test_generator_agent.run(prompt, deps=deps)
    test_yaml = result.output
    print(test_yaml)
    
    # Create safe filename from test name
    filename = f"test_{sanitize_filename(spec.test_name)}.yml"
    file_path = Path("tests") / filename
    
    # Ensure the tests directory exists
    os.makedirs("tests", exist_ok=True)
    
    # Generate a header comment with all user-provided details
    header = f"""# {spec.test_name}
# This test simulates {spec.alert_type} on a {spec.device_type}
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 
# Original Input Details:
# Test Name: {spec.test_name}
# Alert Type: {spec.alert_type}
# Device Type: {spec.device_type}
# Description: {spec.description}"""

    # Add raw event to header if provided
    if spec.raw_event:
        header += f"""
# Raw Event: {spec.raw_event}"""

    # Add root cause to header if provided
    if spec.root_cause:
        header += f"""
# Root Cause: {spec.root_cause}"""
        
    header += "\n\n"

    # Write the YAML file with the header comment
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(header)
        
        # Create a custom yaml representer for multi-line strings
        def str_presenter(dumper, data):
            if '\n' in data:
                # Use the literal style (|) for multi-line strings
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            return dumper.represent_scalar('tag:yaml.org,2002:str', data)
        
        # Register the custom representer
        yaml.add_representer(str, str_presenter)
        
        # Dump the data with the pipe style for multi-line strings
        yaml.dump(
            {
                "alert_payload": test_yaml.alert_payload,
                "custom_instructions": test_yaml.custom_instructions,
                "expected_rca": test_yaml.expected_rca,
                "commands": test_yaml.commands,
                "device_facts": test_yaml.device_facts
            },
            f,
            default_flow_style=False,
            sort_keys=False,
        )
    
    print(f"Test file generated successfully: {file_path}")
    return file_path


def get_test_spec_from_user() -> TestSpec:
    """
    Prompt the user for test specifications and return a TestSpec object.
    
    Returns:
        TestSpec: Object containing the user-provided test specifications
    """
    print("=== Network Troubleshooting Test Generator ===")
    print("Please provide details for the test scenario:\n")
    
    test_name = input("Test Name (e.g., BGP Flap): ")
    alert_type = input("Alert Type (e.g., BGP flap, interface down): ")
    device_type = input("Device Type (e.g., NCS 5508, Nexus 9236C, Catalyst 9348, Cisco 8808): ")
    description = input("Description (detailed description of the issue): ")
    root_cause = input("Root Cause (specify the underlying cause of the issue, leave blank if not known): ")
    raw_event = input("Raw Event (optional - raw event details such as syslog message, leave blank if none): ")
    
    return TestSpec(
        test_name=test_name,
        alert_type=alert_type,
        device_type=device_type,
        description=description,
        root_cause=root_cause if root_cause else None,
        raw_event=raw_event if raw_event else None
    )


async def main():
    """
    Main function to run the test generator.
    """
    try:
        print("=== Network Troubleshooting Test Generator ===")
        print("\nWhat would you like to do?")
        print("1. Create a new test")
        print("2. Modify an existing test")
        print("3. Exit")
        
        choice = input("\nEnter your choice (1-3): ")
        
        if choice == "1":
            # Get test specifications from user
            spec = get_test_spec_from_user()
            
            # Generate initial test YAML
            print(f"Generating test file for '{spec.test_name}'...")
            print("This may take a moment...")
            
            # Run the test generator agent
            deps = TestGeneratorDeps(debug_mode=False)
            
            # Create prompt with root cause if specified
            prompt = f"""
Generate a complete test YAML file for a network troubleshooting scenario with the following details:

- Test Name: {spec.test_name}
- Alert Type: {spec.alert_type}
- Device Type: {spec.device_type}
- Description: {spec.description}
"""

            # Add raw event to prompt if provided
            if spec.raw_event:
                prompt += f"""
- Raw Event: {spec.raw_event}

"""

            # Add root cause to prompt if provided
            if spec.root_cause:
                prompt += f"""
- Root Cause: {spec.root_cause}

"""

            result = await test_generator_agent.run(prompt, deps=deps)
            test_yaml = result.output
            
            # Preview loop - show content to user and allow editing
            approved = False
            # Store the message history from initial generation
            message_history = result.new_messages()
            
            while not approved:
                # Display the current test content
                print("\n" + "="*80)
                print("GENERATED TEST CONTENT PREVIEW:")
                print("="*80)
                
                print("\nALERT PAYLOAD:")
                print("-"*40)
                print(test_yaml.alert_payload)
                
                print("\nCUSTOM INSTRUCTIONS:")
                print("-"*40)
                print(test_yaml.custom_instructions)
                
                print("\nEXPECTED RCA:")
                print("-"*40)
                print(test_yaml.expected_rca)
                
                print("\nDEVICE FACTS:")
                print("-"*40)
                print(test_yaml.device_facts)
                
                print("\nCOMMANDS:")
                print("-"*40)
                for cmd, output in test_yaml.commands.items():
                    print(f"\nCommand: {cmd}")
                    print("-"*20)
                    print(output)
                    print("-"*20)
                
                print("\n" + "="*80)
                print("Chat with the test generator to modify the test, or approve to save:")
                print("- Type 'approve' to save the test file")
                print("- Type 'modify' to provide instructions for modifying the test")
                print("- Type 'regenerate' to start over with a new test")
                print("- Type 'exit' or 'cancel' to quit without saving")
                
                user_input = input("\nYour input > ")
                
                if user_input.lower() == "approve":
                    approved = True
                elif user_input.lower() == "regenerate":
                    print("Regenerating test content...")
                    result = await test_generator_agent.run(prompt, deps=deps)
                    test_yaml = result.output
                    # Reset message history as this is a fresh generation
                    message_history = result.new_messages()
                elif user_input.lower() in ["exit", "cancel"]:
                    print("Operation cancelled by user.")
                    return 0
                elif user_input.lower() == "modify":
                    # Prompt for free-form instructions
                    edit_prompt = input("Enter your modification instructions > ")
                    # Free-form chat to modify the test
                    print("Updating the test based on your instructions...")
                    edit_result = await test_generator_agent.run(
                        f"The user wants to modify the current network troubleshooting test. Their instructions are:\n\n"
                        f"{edit_prompt}\n\n"
                        f"Make the requested changes to the test and return the complete updated test JSON "
                        f"that includes all necessary components (alert_payload, custom_instructions, expected_rca, commands, and device_facts).",
                        deps=deps,
                        message_history=message_history
                    )
                    test_yaml = edit_result.output
                    # Update message history with this interaction
                    message_history = edit_result.new_messages()
                else:
                    print("Invalid choice! Please type 'approve', 'modify', 'regenerate', 'exit', or 'cancel'.")
            
            # Create and write the test file
            filename = f"test_{sanitize_filename(spec.test_name)}.yml"
            file_path = Path("tests") / filename
            
            # Ensure the tests directory exists
            os.makedirs("tests", exist_ok=True)
            
            # Generate a header comment with all user-provided details
            header = f"""# {spec.test_name}
# This test simulates {spec.alert_type} on a {spec.device_type}
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 
# Original Input Details:
# Test Name: {spec.test_name}
# Alert Type: {spec.alert_type}
# Device Type: {spec.device_type}
# Description: {spec.description}"""

            # Add raw event to header if provided
            if spec.raw_event:
                header += f"""
# Raw Event: {spec.raw_event}"""
                
            # Add root cause to header if provided
            if spec.root_cause:
                header += f"""
# Root Cause: {spec.root_cause}"""
                
            header += "\n\n"

            # Write the YAML file with the header comment
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(header)
                
                # Create a custom yaml representer for multi-line strings
                def str_presenter(dumper, data):
                    if '\n' in data:
                        # Use the literal style (|) for multi-line strings
                        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
                    return dumper.represent_scalar('tag:yaml.org,2002:str', data)
                
                # Register the custom representer
                yaml.add_representer(str, str_presenter)
                
                # Dump the data with the pipe style for multi-line strings
                yaml.dump(
                    {
                        "alert_payload": test_yaml.alert_payload,
                        "custom_instructions": test_yaml.custom_instructions,
                        "expected_rca": test_yaml.expected_rca,
                        "commands": test_yaml.commands,
                        "device_facts": test_yaml.device_facts
                    },
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                )
            
            print(f"\nTest file '{file_path}' has been generated successfully.")
            print("You can use this file with the network troubleshooting workflow by setting:")
            print(f"  test_mode: True")
            print(f"  test_name: {os.path.splitext(os.path.basename(file_path))[0].replace('test_', '')}")
            
        elif choice == "2":
            # List available test files
            test_dir = Path("tests")
            if not test_dir.exists() or not any(test_dir.glob("test_*.yml")):
                print("No existing test files found in the 'tests' directory.")
                return 1
                
            test_files = sorted(list(test_dir.glob("test_*.yml")))
            
            if not test_files:
                print("No test files found in the 'tests' directory.")
                return 1
                
            print("\nAvailable test files:")
            for i, file_path in enumerate(test_files, 1):
                print(f"{i}. {file_path.name}")
                
            file_choice = input("\nEnter the number of the file to modify (or 0 to go back): ")
            
            try:
                file_choice_num = int(file_choice)
                if file_choice_num == 0:
                    print("Operation cancelled.")
                    return 0
                elif 1 <= file_choice_num <= len(test_files):
                    selected_file = test_files[file_choice_num - 1]
                    return await modify_existing_test(str(selected_file))
                else:
                    print("Invalid choice.")
                    return 1
            except ValueError:
                print("Please enter a number.")
                return 1
                
        elif choice == "3":
            print("Exiting.")
            return 0
            
        else:
            print("Invalid choice. Please select 1, 2, or 3.")
            return 1
            
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return 1
    return 0


def load_existing_test(file_path: str) -> TestJSON:
    """
    Load an existing test YAML file and convert it to TestJSON format.
    
    Args:
        file_path: Path to the existing test YAML file
        
    Returns:
        TestJSON: Object containing the test data
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Skip the header lines starting with '#'
            yaml_content = ""
            for line in f:
                if not line.startswith('#'):
                    yaml_content += line
            
            # Parse the YAML content
            test_data = yaml.safe_load(yaml_content)
              # Convert to TestJSON format
            return TestJSON(
                alert_payload=test_data.get('alert_payload', '{}'),
                custom_instructions=test_data.get('custom_instructions', ''),
                expected_rca=test_data.get('expected_rca', ''),
                commands=test_data.get('commands', {}),
                device_facts=test_data.get('device_facts', {})
            )
    except Exception as e:
        raise ValueError(f"Failed to load test file: {str(e)}")


async def modify_existing_test(file_path: str) -> int:
    """
    Load an existing test file, allow the user to modify it using the agent,
    and save the changes back to the file.
    
    Args:
        file_path: Path to the existing test YAML file
        
    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        # Verify the file exists
        if not os.path.isfile(file_path):
            print(f"Error: File '{file_path}' does not exist.")
            return 1
        
        print(f"Loading test file: {file_path}")
        
        # Extract test name from filename for prompt context
        file_name = os.path.basename(file_path)
        test_name = os.path.splitext(file_name)[0].replace('test_', '')
        
        # Load the existing test file
        test_yaml = load_existing_test(file_path)
        
        # Create dependencies
        deps = TestGeneratorDeps(debug_mode=False)
        
        # Create a prompt for the agent to understand the test context        
        prompt = f"""
I'm loading an existing network troubleshooting test named '{test_name}' for you to analyze
and modify as needed. Please become familiar with the test content.

This is an existing test with the following components:

ALERT PAYLOAD:
{test_yaml.alert_payload}

CUSTOM INSTRUCTIONS:
{test_yaml.custom_instructions}

EXPECTED RCA:
{test_yaml.expected_rca}

DEVICE FACTS:
{test_yaml.device_facts}

COMMANDS:
{str(test_yaml.commands)}

Please analyze this test and maintain its structure and format while making any requested modifications.
"""
        
        # Run the agent to analyze the existing test
        result = await test_generator_agent.run(prompt, deps=deps)
        test_yaml = result.output
        
        # Store the message history from initial analysis
        message_history = result.new_messages()
        
        print("Existing test loaded successfully. Ready for modifications.")
        
        # Preview loop - show content to user and allow editing
        approved = False
        
        while not approved:
            # Display the current test content
            print("\n" + "="*80)
            print("TEST CONTENT PREVIEW:")
            print("="*80)
            
            print("\nALERT PAYLOAD:")
            print("-"*40)
            print(test_yaml.alert_payload)
            
            print("\nCUSTOM INSTRUCTIONS:")
            print("-"*40)
            print(test_yaml.custom_instructions)
            
            print("\nEXPECTED RCA:")
            print("-"*40)
            print(test_yaml.expected_rca)
            
            print("\nDEVICE FACTS:")
            print("-"*40)
            print(test_yaml.device_facts)
            
            print("\nCOMMANDS:")
            print("-"*40)
            for cmd, output in test_yaml.commands.items():
                print(f"\nCommand: {cmd}")
                print("-"*20)
                print(output)
                print("-"*20)
            
            print("\n" + "="*80)
            print("Chat with the test generator to modify the test, or approve to save:")
            print("- Type 'approve' to save the test file")
            print("- Type 'modify' to provide instructions for modifying the test")
            print("- Type 'exit' or 'cancel' to quit without saving")
            
            user_input = input("\nYour input > ")
            
            if user_input.lower() == "approve":
                approved = True
            elif user_input.lower() in ["exit", "cancel"]:
                print("Operation cancelled by user.")
                return 0
            elif user_input.lower() == "modify":
                # Prompt for free-form instructions
                edit_prompt = input("Enter your modification instructions > ")
                # Free-form chat to modify the test
                print("Updating the test based on your instructions...")
                edit_result = await test_generator_agent.run(
                    f"The user wants to modify the current network troubleshooting test. Their instructions are:\n\n"
                    f"{edit_prompt}\n\n"
                    f"Make the requested changes to the test and return the complete updated test JSON "
                    f"that includes all necessary components (alert_payload, custom_instructions, expected_rca, commands, and device_facts).",
                    deps=deps,
                    message_history=message_history
                )
                test_yaml = edit_result.output
                # Update message history with this interaction
                message_history = edit_result.new_messages()
            else:
                print("Invalid choice! Please type 'approve', 'modify', 'exit', or 'cancel'.")
        
        # Preserve the original header by reading it from the file
        with open(file_path, 'r', encoding='utf-8') as f:
            header = ""
            for line in f:
                if line.startswith('#'):
                    header += line
                else:
                    # Stop reading once we hit non-comment lines
                    break
            
            # Add modification timestamp to header
            header += f"# Modified on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # Write the modified test back to the file
        with open(file_path, 'w', encoding='utf-8') as f:
            # Write the preserved header
            f.write(header)
            
            # Create a custom yaml representer for multi-line strings
            def str_presenter(dumper, data):
                if '\n' in data:
                    # Use the literal style (|) for multi-line strings
                    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
                return dumper.represent_scalar('tag:yaml.org,2002:str', data)
            
            # Register the custom representer
            yaml.add_representer(str, str_presenter)
            
            # Dump the data with the pipe style for multi-line strings
            yaml.dump(
                {
                    "alert_payload": test_yaml.alert_payload,
                    "custom_instructions": test_yaml.custom_instructions,
                    "expected_rca": test_yaml.expected_rca,
                    "commands": test_yaml.commands,
                    "device_facts": test_yaml.device_facts
                },
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        
        print(f"\nTest file '{file_path}' has been updated successfully.")
        return 0
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return 1
    

if __name__ == "__main__":
    exitcode = asyncio.run(main())
    exit(exitcode)