"""
Utility functions for Netmiko operations.

This module provides helper functions for common Netmiko operations
used by the action executor agent.
"""

import logging
import re

logger = logging.getLogger("action_executor.netmiko_utils")

def parse_device_facts(device_type, output):
    """
    Parse device facts from command output based on device type.
    
    Args:
        device_type (str): The Netmiko device type
        output (str): The output from 'show version' or similar command
        
    Returns:
        dict: Dictionary containing parsed device facts
    """
    facts = {
        'vendor': device_type.split('_')[0] if '_' in device_type else 'unknown',
        'os': device_type,
    }
    
    # Different parsing logic for different device types
    if 'cisco_ios' in device_type or 'cisco_xe' in device_type:
        # Parse Cisco IOS/IOS-XE output
        version_match = re.search(r'Version\s+(\S+),', output)
        if version_match:
            facts['os_version'] = version_match.group(1)
            
        uptime_match = re.search(r'uptime is\s+(.+)', output)
        if uptime_match:
            facts['uptime'] = uptime_match.group(1)
            
        model_match = re.search(r'[Cc]isco\s+(\S+).+\(.*\)\s+processor', output)
        if model_match:
            facts['model'] = model_match.group(1)
            
        serial_match = re.search(r'[Pp]rocessor board ID\s+(\S+)', output)
        if serial_match:
            facts['serial_number'] = serial_match.group(1)
            
    elif 'cisco_xr' in device_type:
        # Parse Cisco IOS-XR output
        version_match = re.search(r'Version\s*:\s*(\S+)', output)
        if version_match:
            facts['os_version'] = version_match.group(1)
            
        model_match = re.search(r'cisco\s+(\S+)\s+\(', output, re.IGNORECASE)
        if model_match:
            facts['model'] = model_match.group(1)
            
    elif 'cisco_nxos' in device_type:
        # Parse Cisco NX-OS output
        version_match = re.search(r'NXOS:\s+version\s+(\S+)', output)
        if version_match:
            facts['os_version'] = version_match.group(1)
            
        model_match = re.search(r'Hardware\s+cisco\s+(\S+\s+\S+)', output)
        if model_match:
            facts['model'] = model_match.group(1)
    
    elif 'juniper' in device_type:
        # Parse Juniper output
        model_match = re.search(r'Model:\s+(\S+)', output)
        if model_match:
            facts['model'] = model_match.group(1)
            
        version_match = re.search(r'JUNOS\s+\S+\s+\[(\S+)\]', output)
        if version_match:
            facts['os_version'] = version_match.group(1)
    
    return facts

def get_interface_list(netmiko_conn, device_type):
    """
    Get list of interfaces based on device type.
    
    Args:
        netmiko_conn: Netmiko connection object
        device_type (str): The Netmiko device type
        
    Returns:
        list: List of interface names
    """
    interface_list = []
    
    try:
        if 'cisco_ios' in device_type or 'cisco_xe' in device_type:
            output = netmiko_conn.send_command('show ip interface brief')
            for line in output.splitlines()[1:]:  # Skip header
                parts = line.split()
                if parts:
                    interface_list.append(parts[0])
                    
        elif 'cisco_xr' in device_type:
            output = netmiko_conn.send_command('show ipv4 interface brief')
            for line in output.splitlines()[1:]:  # Skip header
                parts = line.split()
                if parts:
                    interface_list.append(parts[0])
                    
        elif 'cisco_nxos' in device_type:
            output = netmiko_conn.send_command('show interface brief')
            for line in output.splitlines()[1:]:  # Skip header
                parts = line.split()
                if parts:
                    interface_list.append(parts[0])
                    
        elif 'juniper' in device_type:
            output = netmiko_conn.send_command('show interfaces terse')
            for line in output.splitlines()[1:]:  # Skip header
                parts = line.split()
                if parts:
                    interface_list.append(parts[0])
    except Exception as e:
        logger.warning(f"Error getting interface list: {str(e)}")
    
    return interface_list
