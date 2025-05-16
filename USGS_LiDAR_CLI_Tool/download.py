#!/usr/bin/env python3
"""
USGS LiDAR Download Module

This module handles downloading LAZ files from USGS LiDAR datasets
in Entwine Point Tile (EPT) format using PDAL pipelines.
"""

import os
import sys
import json
import time
import logging
import tempfile
import subprocess
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple

logger = logging.getLogger(__name__)


def get_ept_bounds(ept_url: str) -> Optional[List[float]]:
    """
    Get bounds of an EPT dataset by downloading and parsing the ept.json file.
    
    Args:
        ept_url: URL to the EPT dataset
        
    Returns:
        list: [minx, miny, maxx, maxy] if successful, None otherwise
    """
    try:
        logger.info(f"Fetching EPT metadata from {ept_url}")
        
        # Create a temporary file to store the ept.json content
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            try:
                # Download the file using curl command
                cmd = ["curl", "-s", ept_url]
                result = subprocess.run(cmd, capture_output=True, check=True)
                
                if result.returncode != 0:
                    logger.error(f"Error downloading EPT metadata: {result.stderr.decode()}")
                    return None
                
                # Write the content to the temporary file
                temp_file.write(result.stdout)
                temp_file.flush()
                
                # Parse the JSON file
                with open(temp_file.name, 'r') as f:
                    ept_data = json.load(f)
                
                # Extract bounds from the ept.json file
                if 'bounds' in ept_data:
                    bounds = ept_data['bounds']
                    # Handle different bounds formats
                    if isinstance(bounds, list):
                        if len(bounds) >= 6:
                            # Standard format with XYZ min/max: [xmin, ymin, zmin, xmax, ymax, zmax]
                            return [
                                bounds[0], bounds[1],  # minx, miny
                                bounds[3], bounds[4]   # maxx, maxy
                            ]
                        elif len(bounds) >= 4:
                            # XY min/max only: [xmin, ymin, xmax, ymax]
                            return bounds[:4]
                    elif isinstance(bounds, dict):
                        # Dictionary format with explicit keys
                        if all(k in bounds for k in ['minx', 'miny', 'maxx', 'maxy']):
                            return [
                                bounds['minx'], bounds['miny'],
                                bounds['maxx'], bounds['maxy']
                            ]
                        # Handle cubic bounds format
                        elif all(k in bounds for k in ['xmin', 'ymin', 'xmax', 'ymax']):
                            return [
                                bounds['xmin'], bounds['ymin'],
                                bounds['xmax'], bounds['ymax']
                            ]
            finally:
                # Clean up
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
        
        logger.error("Could not extract bounds from ept.json")
        return None
    
    except Exception as e:
        logger.error(f"Error getting EPT bounds: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Default bounds as last resort
        return None


def create_pdal_pipeline(input_url: str, output_laz: str, 
                        boundary_geojson: Optional[Dict[str, Any]] = None,
                        bounds: Optional[List[float]] = None, 
                        resolution: Optional[Union[float, str]] = None) -> Dict[str, Any]:
    """
    Create a PDAL pipeline definition for processing EPT data.
    
    Args:
        input_url: URL to the EPT dataset
        output_laz: Path to the output LAZ file
        boundary_geojson: Optional GeoJSON boundary to limit processing
        bounds: Optional bounds to limit processing [minx, miny, maxx, maxy]
        resolution: Optional resolution parameter
        
    Returns:
        dict: PDAL pipeline definition
    """
    # Create a pipeline definition
    reader = {
        "type": "readers.ept",
        "filename": input_url
    }
    
    # If boundary_geojson is provided, use the polygon parameter for precise filtering
    if boundary_geojson:
        # Extract geometry from the GeoJSON
        geometry = None
        if boundary_geojson.get('type') == 'FeatureCollection':
            if boundary_geojson.get('features') and len(boundary_geojson['features']) > 0:
                geometry = boundary_geojson['features'][0].get('geometry')
        elif boundary_geojson.get('type') == 'Feature':
            geometry = boundary_geojson.get('geometry')
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon']:
            geometry = boundary_geojson
            
        if geometry:
            # Convert to JSON string and use as polygon parameter
            reader["polygon"] = json.dumps(geometry)
    # Fall back to bounds if no geometry is available
    elif bounds:
        bounds_str = f"([{bounds[0]}, {bounds[2]}], [{bounds[1]}, {bounds[3]}])"
        reader["bounds"] = bounds_str
    
    # Create the pipeline
    pipeline = {
        "pipeline": [
            reader,
            {
                "type": "writers.las",
                "filename": output_laz,
                "minor_version": 4,
                "dataformat_id": 8
            }
        ]
    }
    
    # Apply resolution if specified
    if resolution is not None and resolution != "full":
        try:
            pipeline["pipeline"][0]["resolution"] = float(resolution)
        except (ValueError, TypeError):
            logger.warning(f"Invalid resolution value: {resolution}. Using default.")
    
    return pipeline


def run_pdal_pipeline(pipeline: Dict[str, Any], min_points: int = 100) -> Tuple[bool, int]:
    """
    Run a PDAL pipeline using subprocess.
    
    Args:
        pipeline: PDAL pipeline definition
        min_points: Minimum number of points required for a successful result
        
    Returns:
        tuple: (success, point_count)
    """
    try:
        # Create a temporary pipeline JSON file with unique name
        temp_id = str(time.time()).replace('.', '') + str(os.getpid())
        pipeline_file = f"temp_pipeline_{temp_id}.json"
        
        with open(pipeline_file, "w") as f:
            json.dump(pipeline, f, indent=4)
            
        # Run PDAL pipeline using subprocess
        cmd = ["pdal", "pipeline", pipeline_file]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Clean up temporary file
        try:
            os.remove(pipeline_file)
        except:
            pass
        
        laz_file = pipeline["pipeline"][-1]["filename"]
        
        if result.returncode == 0:
            # Check if the file has enough points
            point_count = get_point_count(laz_file)
            
            if point_count >= min_points:
                return True, point_count
            else:
                # Clean up the file if it exists but has too few points
                if os.path.exists(laz_file) and point_count < min_points:
                    os.remove(laz_file)
                return False, point_count
        else:
            logger.error(f"PDAL pipeline failed: {result.stderr}")
            return False, 0
            
    except Exception as e:
        logger.error(f"Error running PDAL pipeline: {str(e)}")
        return False, 0


def get_point_count(laz_file: str) -> int:
    """
    Get the point count from a LAZ file using PDAL info.
    
    Args:
        laz_file: Path to the LAZ file
        
    Returns:
        int: Number of points in the file, 0 if error or file doesn't exist
    """
    try:
        if not os.path.exists(laz_file):
            return 0
            
        cmd = ["pdal", "info", "--summary", laz_file]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        if result.returncode == 0:
            # Parse the JSON output to get point count
            summary = json.loads(result.stdout)
            if 'summary' in summary and 'num_points' in summary['summary']:
                return summary['summary']['num_points']
        
        return 0
    except Exception as e:
        logger.warning(f"Error getting point count from {laz_file}: {str(e)}")
        return 0


def create_processing_tiles(bounds: List[float], tile_size: float = 1000) -> List[List[float]]:
    """
    Create processing tiles from bounds.
    
    Args:
        bounds: [minx, miny, maxx, maxy]
        tile_size: Size of tile in units (default: 1000)
        
    Returns:
        list: List of tile bounds [[minx, miny, maxx, maxy], ...]
    """
    minx, miny, maxx, maxy = bounds
    
    # Calculate number of tiles in each direction
    num_x_tiles = max(1, int((maxx - minx) / tile_size))
    num_y_tiles = max(1, int((maxy - miny) / tile_size))
    
    # Adjust tile size to cover the entire area
    x_tile_size = (maxx - minx) / num_x_tiles
    y_tile_size = (maxy - miny) / num_y_tiles
    
    # Create tiles
    tiles = []
    for i in range(num_x_tiles):
        for j in range(num_y_tiles):
            tile_minx = minx + i * x_tile_size
            tile_miny = miny + j * y_tile_size
            tile_maxx = minx + (i + 1) * x_tile_size
            tile_maxy = miny + (j + 1) * y_tile_size
            
            tiles.append([tile_minx, tile_miny, tile_maxx, tile_maxy])
    
    return tiles


def download_dataset(boundary_geojson: Dict[str, Any], dataset: Dict[str, Any], 
                    output_dir: str, config: Dict[str, Any], geojson_filename: str = None) -> List[str]:
    """
    Download LAZ files from a USGS LiDAR dataset that intersect with the boundary.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        dataset: Dataset information dictionary with name, url, s3_url
        output_dir: Directory to save the LAZ files
        config: Configuration dictionary
        geojson_filename: Optional name to use for the output file (without extension)
        
    Returns:
        list: List of paths to downloaded LAZ files
    """
    try:
        # Extract dataset information
        dataset_name = dataset.get('name', 'unknown')
        s3_url = dataset.get('s3_url')
        
        if not s3_url:
            logger.error(f"No S3 URL available for dataset: {dataset_name}")
            return []
        
        # Determine AWS region (default to us-west-2)
        region = config.get('region', 'us-west-2')
        
        # Construct EPT URL
        ept_url = f"https://s3-{region}.amazonaws.com/{s3_url}/ept.json"
        logger.info(f"Using EPT URL: {ept_url}")
        
        # Determine resolution
        resolution = config.get('resolution')
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Set up processing parameters
        min_points = config.get('min_points', 100)
        
        # Use the geojson filename if provided, otherwise use the dataset name
        output_filename = geojson_filename if geojson_filename else dataset_name
        
        # Create a single output file for the dataset
        output_file = os.path.join(output_dir, f"{output_filename}.laz")
        
        # Create pipeline using the boundary directly
        pipeline = create_pdal_pipeline(
            input_url=ept_url,
            output_laz=output_file,
            boundary_geojson=boundary_geojson,
            resolution=resolution
        )
        
        # Run the pipeline
        logger.info(f"Processing dataset: {dataset_name}")
        success, point_count = run_pdal_pipeline(pipeline, min_points)
        
        if success:
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # Convert to MB
            logger.info(f"Dataset {dataset_name}: {file_size:.2f} MB, {point_count} points")
            return [output_file]
        else:
            if point_count == 0:
                logger.info(f"Dataset {dataset_name}: No points found in the boundary area")
            else:
                logger.info(f"Dataset {dataset_name}: Only {point_count} points (below threshold)")
            return []
    
    except Exception as e:
        logger.error(f"Error downloading dataset: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def download_lidar_data(boundary_geojson: Dict[str, Any], dataset: Dict[str, Any], 
                       output_dir: str, config: Dict[str, Any], geojson_filename: str = None) -> List[str]:
    """
    Download LAZ files based on the input boundary.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        dataset: Dataset information dictionary
        output_dir: Directory to save the LAZ files
        config: Configuration dictionary
        geojson_filename: Optional name to use for the output file (without extension)
        
    Returns:
        list: List of paths to downloaded LAZ files
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Download data from the dataset
    return download_dataset(boundary_geojson, dataset, output_dir, config, geojson_filename)


def merge_laz_files(input_files: List[str], output_file: str, year_mapping: Dict[str, float] = None) -> bool:
    """
    Merge multiple LAZ files into a single file using PDAL.
    
    Args:
        input_files: List of input LAZ file paths
        output_file: Path to the output merged LAZ file
        year_mapping: Optional dictionary mapping filenames to years for adding a Year dimension
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if not input_files:
            logger.error("No input files provided for merging")
            return False
        
        logger.info(f"Merging {len(input_files)} LAZ files into {output_file}")
        
        # Create a PDAL pipeline for merging
        pipeline = {
            "pipeline": []
        }
        
        # Add readers for each file, with extra attribute if year_mapping is provided
        for i, file_path in enumerate(input_files):
            reader = {
                "type": "readers.las",
                "filename": file_path,
                "tag": f"reader{i}"
            }
            
            pipeline["pipeline"].append(reader)
            
            # If year mapping is provided, add an assignment filter to create a Year dimension
            if year_mapping and file_path in year_mapping:
                year_value = year_mapping[file_path]
                pipeline["pipeline"].append({
                    "type": "filters.assign",
                    "assignment": f"Year[1:1]={year_value}",
                    "tag": f"assign{i}",
                    "inputs": [f"reader{i}"]
                })
        
        # Create inputs list for the merge filter
        if year_mapping:
            inputs = [f"assign{i}" for i in range(len(input_files))]
        else:
            inputs = [f"reader{i}" for i in range(len(input_files))]
            
        # Add merge filter if there are multiple files
        if len(input_files) > 1:
            pipeline["pipeline"].append(
                {
                    "type": "filters.merge",
                    "inputs": inputs,
                    "tag": "merged"
                }
            )
            
            # Add writer with merged input
            pipeline["pipeline"].append(
                {
                    "type": "writers.las",
                    "filename": output_file,
                    "inputs": ["merged"],
                    "extra_dims": "all" if year_mapping else None
                }
            )
        else:
            # Add writer directly for a single file
            pipeline["pipeline"].append(
                {
                    "type": "writers.las",
                    "filename": output_file,
                    "inputs": [inputs[0]],
                    "extra_dims": "all" if year_mapping else None
                }
            )
        
        # Create a temporary pipeline JSON file
        pipeline_file = "temp_merge_pipeline.json"
        with open(pipeline_file, "w") as f:
            json.dump(pipeline, f, indent=4)
        
        # Run the pipeline
        cmd = ["pdal", "pipeline", pipeline_file]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Clean up temporary file
        try:
            os.remove(pipeline_file)
        except:
            pass
        
        if result.returncode == 0:
            if os.path.exists(output_file):
                # Get point count of merged file
                point_count = get_point_count(output_file)
                file_size = os.path.getsize(output_file) / (1024 * 1024)  # Convert to MB
                logger.info(f"Successfully merged files: {file_size:.2f} MB, {point_count} points")
                return True
            else:
                logger.error("Merge process completed but output file not found")
                return False
        else:
            logger.error(f"Error merging files: {result.stderr}")
            return False
    
    except Exception as e:
        logger.error(f"Error merging LAZ files: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
