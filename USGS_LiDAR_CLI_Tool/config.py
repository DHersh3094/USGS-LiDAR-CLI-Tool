#!/usr/bin/env python3
"""
Configuration module for USGS LiDAR Downloader

Handles loading and validation of configuration settings.
"""

import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "tile_size": 1000,  # meters
    "resolution": None,  # None means native/full resolution
    "download_workers": 8,
    "min_points": 100,
    "region": "us-west-2"
}


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from a JSON file.
    If the file doesn't exist, create it with default values.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        dict: Configuration dictionary
    """
    # Start with default configuration
    config = DEFAULT_CONFIG.copy()
    
    # If config file exists, load it
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
            
            # Update default config with user configuration
            config.update(user_config)
            logger.info(f"Loaded configuration from {config_path}")
            
        except Exception as e:
            logger.warning(f"Error loading configuration from {config_path}: {str(e)}")
            logger.warning(f"Using default configuration")
    else:
        # Create default configuration file if it doesn't exist
        try:
            with open(config_path, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            logger.info(f"Created default configuration file at {config_path}")
        except Exception as e:
            logger.warning(f"Error creating default configuration file: {str(e)}")
    
    # Validate and return configuration
    return validate_config(config)


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate configuration settings.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        dict: Validated configuration dictionary
    """
    # Ensure tile_size is a positive number
    if "tile_size" in config:
        try:
            config["tile_size"] = float(config["tile_size"])
            if config["tile_size"] <= 0:
                logger.warning("Invalid tile_size (must be positive). Using default value.")
                config["tile_size"] = DEFAULT_CONFIG["tile_size"]
        except (ValueError, TypeError):
            logger.warning("Invalid tile_size value. Using default value.")
            config["tile_size"] = DEFAULT_CONFIG["tile_size"]
    
    # Validate resolution
    if "resolution" in config and config["resolution"] is not None:
        if config["resolution"] != "full":
            try:
                config["resolution"] = float(config["resolution"])
                if config["resolution"] <= 0:
                    logger.warning("Invalid resolution (must be positive). Using full resolution.")
                    config["resolution"] = None
            except (ValueError, TypeError):
                logger.warning("Invalid resolution value. Using full resolution.")
                config["resolution"] = None
        elif config["resolution"] == "full":
            # Set to None for internal consistency
            config["resolution"] = None
    
    # Ensure download_workers is a positive integer
    if "download_workers" in config:
        try:
            config["download_workers"] = int(config["download_workers"])
            if config["download_workers"] <= 0:
                logger.warning("Invalid download_workers (must be positive). Using default value.")
                config["download_workers"] = DEFAULT_CONFIG["download_workers"]
        except (ValueError, TypeError):
            logger.warning("Invalid download_workers value. Using default value.")
            config["download_workers"] = DEFAULT_CONFIG["download_workers"]
    
    # Ensure min_points is a non-negative integer
    if "min_points" in config:
        try:
            config["min_points"] = int(config["min_points"])
            if config["min_points"] < 0:
                logger.warning("Invalid min_points (must be non-negative). Using default value.")
                config["min_points"] = DEFAULT_CONFIG["min_points"]
        except (ValueError, TypeError):
            logger.warning("Invalid min_points value. Using default value.")
            config["min_points"] = DEFAULT_CONFIG["min_points"]
    
    return config
