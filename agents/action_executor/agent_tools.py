from __future__ import annotations as _annotations

import logging
from typing import Any
import asyncio
from netmiko import ConnectHandler

from pydantic_ai import RunContext, ModelRetry
from utils.netmiko_utils import parse_device_facts, get_interface_list

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("action_executor.agent_tools")

async def execute_cli_commands(ctx: RunContext, commands: list[str]) -> dict:
    """
    Execute CLI commands on a network device using Netmiko.
    
    Takes a list of commands and executes them on the device.
    Note: This tool should only be used when simulation_mode is False.

    Args:
        ctx: The run context containing dependencies (device_driver).
        commands: List of CLI commands to execute.

    Returns:
        A dictionary mapping each command to its output.
    """

    commands = ctx.deps.current_step.commands
    logger.info(f"Executing CLI commands: {commands}")
    
    # Get netmiko connection from dependencies - this is the global NETMIKO_CONNECTION object
    netmiko_conn = ctx.deps.device_driver
    
    results = {}
    errors = []
    
    try:
        # Check if netmiko_conn is None (simulation mode)
        if netmiko_conn is None:
            error_msg = "No valid Netmiko connection available. Unable to execute command."
            logger.warning(error_msg)
            for command in commands:
                results[command] = f"ERROR: {error_msg}"
            return results

        # Execute commands using Netmiko
        for command in commands:
            try:
                # Use Netmiko's send_command method to execute the command
                output = netmiko_conn.send_command(command)
                results[command] = output
            except Exception as e:
                error_msg = f"Error executing command '{command}': {str(e)}"
                logger.error(error_msg)
                results[command] = f"ERROR: {error_msg}"
                errors.append(error_msg)
          # If there were errors, log them
        if errors:
            logger.error(f"Encountered {len(errors)} errors while executing commands")
        
        return results
        
    except Exception as e:
        error_msg = f"Unexpected error executing CLI commands: {str(e)}"
        logger.exception(error_msg)
        # Return error for all commands
        for command in commands:
            results[command] = f"ERROR: {error_msg}"
        return results

async def execute_cli_config(ctx: RunContext, commands: list[str]) -> dict:
    """
    Execute configuration commands on a network device using Netmiko.
    
    Uses Netmiko's send_config_set() method to apply configuration.
    Note: This tool should only be used when simulation_mode is False.

    Args:
        ctx: The run context containing dependencies (device_driver and current_step).

    Returns:
        A dictionary with the config commands as key and success/failure message as value.
    """
    # Get the commands from current_step
    commands = ctx.deps.current_step.commands.copy()
    logger.info(f"Executing config commands: {commands}")
    
    # Get netmiko connection from dependencies
    netmiko_conn = ctx.deps.device_driver
    
    # Initialize results dictionary
    results = {}
    
    try:
        # Check if netmiko_conn is None (simulation mode)
        if netmiko_conn is None:
            error_msg = "No valid Netmiko connection available. Unable to apply configuration."
            logger.warning(error_msg)
            config_str = "\n".join(commands)
            results[config_str] = f"ERROR: {error_msg}"
            return results

        # Check if the first command contains "conf" and remove it if so
        # (not needed for Netmiko as it handles config mode automatically)
        if commands and ("conf" in commands[0].lower() or "config" in commands[0].lower()):
            logger.info(f"Removing configuration mode command: {commands[0]}")
            commands.pop(0)
        
        if not commands:
            logger.warning("No configuration commands to apply after filtering")
            results["No configuration commands"] = "ERROR: No configuration commands to apply"
            return results
            
        # Combine all commands into a single string for logging
        config_str = "\n".join(commands)
        
        try:
            # Enter config mode and apply configuration
            output = netmiko_conn.send_config_set(commands)
            
            # Check if there was an error in the output
            if "invalid" in output.lower() or "error" in output.lower() or "failed" in output.lower():
                logger.warning(f"Possible error detected in configuration output: {output}")
                results[config_str] = f"WARNING: Possible error in configuration: {output}"
            else:
                success_msg = "Configuration applied successfully"
                logger.info(success_msg)
                results[config_str] = success_msg
            
            # Save the configuration if applicable (depends on device type)
            try:
                if hasattr(netmiko_conn, 'save_config'):
                    netmiko_conn.save_config()
                    logger.info("Configuration saved")
            except Exception as save_error:
                logger.warning(f"Note: Could not save configuration: {str(save_error)}")
            
        except Exception as e:
            error_msg = f"Error applying configuration: {str(e)}"
            logger.error(error_msg)
            results[config_str] = f"ERROR: {error_msg}"
        
        return results
        
    except Exception as e:
        error_msg = f"Unexpected error executing configuration commands: {str(e)}"
        logger.exception(error_msg)
        config_str = "\n".join(commands)
        results[config_str] = f"ERROR: {error_msg}"
        return results