from __future__ import annotations as _annotations
import os
import json
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from pydantic_ai import Agent, RunContext

from .agent_prompts import RESULT_SUMMARY_SYSTEM_PROMPT
from ..models import FaultSummary, TroubleshootingStep, ResultSummary, ResultSummaryDependencies

# Load environment variables from .env file
load_dotenv()

# Initialize the Result Summary agent with structured output
agent = Agent(
    model='openai:gpt-4.1',
    system_prompt=RESULT_SUMMARY_SYSTEM_PROMPT,
    output_type=ResultSummary,
    deps_type=ResultSummaryDependencies,
    retries=2,
    instrument=True,
)

# Define a dynamic system prompt that incorporates the golden rules
@agent.system_prompt
def add_golden_rules(ctx: RunContext[ResultSummaryDependencies]) -> str:
    """Add any configured golden rules to the system prompt."""
    if "golden_rules" in ctx.deps.settings and ctx.deps.settings["golden_rules"]:
        # Format golden rules as numbered list
        golden_rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(ctx.deps.settings["golden_rules"])])
        return f"**GOLDEN RULES**\nThe following rules must always be followed during execution:\n{golden_rules_text}"
    return "No golden rules defined."

async def run(deps: Optional[ResultSummaryDependencies] = None):
    """
    Run the result summary agent.
    
    Args:
        deps: Dependencies for the agent, including fault summary, action plan history, 
              device facts, settings, and logger
        
    Returns:
        The agent's response object containing the structured ResultSummary
    """
    # Initialize dependencies if None
    if deps is None:
        deps = ResultSummaryDependencies()
    
    # Log debug information if debug mode is enabled
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Result Summary Agent Execution", extra={
            "fault_summary": deps.fault_summary,
            "action_plan_history_length": len(deps.action_plan_history) if deps.action_plan_history else 0
        })      # Create the JSON input data structure
    input_data = {
        "current_step": deps.current_step.model_dump() if deps.current_step else None,
        "current_step_index": deps.current_step_index,
        "alert_raw_data": deps.alert_raw_data,
        "fault_summary": {
            "title": deps.fault_summary.title if deps.fault_summary else None,
            "summary": deps.fault_summary.summary if deps.fault_summary else None,
            "hostname": deps.fault_summary.hostname if deps.fault_summary else None,
            "timestamp": deps.fault_summary.timestamp.isoformat() if deps.fault_summary and deps.fault_summary.timestamp else None,
            "severity": deps.fault_summary.severity if deps.fault_summary else None,
            "metadata": deps.fault_summary.metadata if deps.fault_summary else {}
        },
        "device_facts": deps.device_facts,
        "action_plan_history": [step.model_dump() for step in deps.action_plan_history],
        "action_plan_remaining": [step.model_dump() for step in deps.action_plan_remaining],
        "settings": {k: v for k, v in deps.settings.items() if k != "logger"}  # Exclude logger as it's not serializable
    }
    
    # Format the user prompt with the input data
    user_prompt = (
        f"Generate a comprehensive summary of the network troubleshooting session based on the following data:\n\n"
        f"```json\n{json.dumps(input_data, indent=2)}\n```\n\n"
        f"Analyze the execution history to determine the resolution status, key findings, successful and failed actions, "
        f"and provide recommendations for next steps if the issue is not fully resolved."
    )
    
    # Run the agent with the user prompt
    response = await agent.run(user_prompt, deps=deps)
    
    return response
