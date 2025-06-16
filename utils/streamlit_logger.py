import logging
import streamlit as st
from typing import Dict, Any, Optional

class StreamlitLogger(logging.Logger):
    """Custom logger that writes to both standard logging and Streamlit UI when in debug mode"""
    
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)
        # Initialize log storage in session state if not exists
        if "debug_logs" not in st.session_state:
            st.session_state.debug_logs = []
    
    def _log_to_streamlit(self, level: int, msg: str, *args, **kwargs):
        # Only log if we're in debug mode
        settings = st.session_state.get("settings", {"debug_mode": False})
        if not settings.get("debug_mode", False):
            return
            
        # Format the message if args are provided
        if args:
            msg = msg % args
            
        # Add extra context if provided
        extras = {}
        if "extra" in kwargs and kwargs["extra"] is not None:
            extras = kwargs["extra"]
            
        # Format the log message for display
        formatted_msg = self._format_log_message(level, msg, extras)
        
        # Add to current message if we're inside a response
        if "current_response" in st.session_state and st.session_state.current_response is not None:
            st.session_state.current_response += "\n\n" + formatted_msg
        
        # Always add to debug logs for record keeping
        st.session_state.debug_logs.append({
            "level": level,
            "message": msg,
            "extras": extras,
            "formatted": formatted_msg
        })
    
    def _format_log_message(self, level: int, msg: str, extras: Dict[str, Any]) -> str:
        """Format a log message for display in the chat window"""
        level_name = logging.getLevelName(level)
        
        # Create a nicely formatted debug message
        formatted = f"**[DEBUG]** `{level_name}`: {msg}"
        
        # Add formatted extras if they exist
        if extras:
            # Special handling for system_prompt and user_input
            if "system_prompt" in extras:
                formatted += "\n\n<details><summary>System Prompt</summary>\n\n```\n"
                formatted += extras["system_prompt"]
                formatted += "\n```\n</details>"
            
            if "user_input" in extras:
                formatted += "\n\n<details><summary>User Input</summary>\n\n```\n"
                formatted += extras["user_input"] 
                formatted += "\n```\n</details>"
            
            # Add any other extras as JSON
            other_extras = {k: v for k, v in extras.items() 
                          if k not in ["system_prompt", "user_input"]}
            
            if other_extras:
                formatted += "\n\n<details><summary>Additional Details</summary>\n\n```json\n"
                # Format as a simple string representation
                formatted += str(other_extras).replace("'", '"') 
                formatted += "\n```\n</details>"
        
        return formatted
    
    def debug(self, msg, *args, **kwargs):
        self._log_to_streamlit(logging.DEBUG, msg, *args, **kwargs)
        super().debug(msg, *args, **kwargs)
        
    def info(self, msg, *args, **kwargs):
        self._log_to_streamlit(logging.INFO, msg, *args, **kwargs)
        super().info(msg, *args, **kwargs)
        
    def warning(self, msg, *args, **kwargs):
        self._log_to_streamlit(logging.WARNING, msg, *args, **kwargs)
        super().warning(msg, *args, **kwargs)
        
    def error(self, msg, *args, **kwargs):
        self._log_to_streamlit(logging.ERROR, msg, *args, **kwargs)
        super().error(msg, *args, **kwargs)
        
    def critical(self, msg, *args, **kwargs):
        self._log_to_streamlit(logging.CRITICAL, msg, *args, **kwargs)
        super().critical(msg, *args, **kwargs)


def get_streamlit_logger(name: str) -> StreamlitLogger:
    """Get a StreamlitLogger instance with the given name"""
    # Remove any existing handlers to avoid duplicates
    logger = StreamlitLogger(name)
    
    # Add a handler for standard output too
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger