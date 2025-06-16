import os
from typing import List
import json

import logfire
from pydantic_ai import Agent, RunContext

from .agent_prompts import SYSTEM_PROMPT
from ..models import FaultSummary, TroubleshootingStep, ActionPlannerDependencies

# Logfire instrumentation is enabled if API key is set
logfire_api_key = os.getenv('LOGFIRE_KEY')
logfire.configure(send_to_logfire='if-token-present')
    
# Create the agent with type-safe output and instructions
action_planner = Agent(
    model="openai:o4-mini",
    system_prompt=SYSTEM_PROMPT,
    output_type=List[TroubleshootingStep],
    deps_type=ActionPlannerDependencies,
    instrument=True,
)

# Define a dynamic system prompt that incorporates the golden rules
@action_planner.system_prompt
def add_golden_rules(ctx: RunContext[ActionPlannerDependencies]) -> str:
    """Add any configured golden rules to the system prompt."""
    if "golden_rules" in ctx.deps.settings and ctx.deps.settings["golden_rules"]:
        # Format golden rules as numbered list
        golden_rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(ctx.deps.settings["golden_rules"])])
        return f"**GOLDEN RULES**\nThe following rules must always be followed during execution:\n{golden_rules_text}"
    return "No golden rules defined."

async def run(user_input: str, deps: ActionPlannerDependencies) -> RunContext:
    """
    Run the action planner agent with the given user input.
    
    Args:
        user_input: A description of the network fault
        deps: Dependencies including fault_summary, settings, logger, and latest_user_message
        
    Returns:
        The agent's response object containing the list of TroubleshootingStep items
    """
    # Initialize settings if None in dependencies
    if deps.settings is None:
        deps.settings = {"debug_mode": False, "simulation_mode": True}
    
    # Log debug information if debug mode is enabled
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Action Planner Agent User Prompt", extra={
            "user_input": user_input
        })

    # Manually extract fault_summary fields to avoid datetime serialization issues
    fault_summary_dict = {
        "title": deps.fault_summary.title,
        "summary": deps.fault_summary.summary,
        "hostname": deps.fault_summary.hostname,
        "timestamp": deps.fault_summary.timestamp.isoformat() if deps.fault_summary.timestamp else None,
        "severity": deps.fault_summary.severity,
        "metadata": deps.fault_summary.metadata
    }
    
    # Format the input according to the template
    formatted_input = f"fault_summary:\n{json.dumps(fault_summary_dict)}\n\n"
    formatted_input += f"device_facts:\n{json.dumps(deps.device_facts)}\n\n"
    formatted_input += f"max_steps: {deps.settings['max_steps']}\n\n"
    
    if deps.custom_instructions:
        formatted_input += f"custom_instructions:\n{deps.custom_instructions}"
    else:
        formatted_input += "custom_instructions:\n"  # Empty but present

    return await action_planner.run(formatted_input, deps=deps)
