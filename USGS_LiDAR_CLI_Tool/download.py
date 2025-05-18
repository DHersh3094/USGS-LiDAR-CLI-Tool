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
import io
import numpy as np
from typing import List, Dict, Any, Optional, Union, Tuple

# Set up logger
logger = logging.getLogger(__name__)

# Debug Python environment
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Python version: {sys.version}")

# Try to import laspy - will be used to add Year VLR
try:
    import laspy
    import numpy as np
    LASPY_AVAILABLE = True
    logger.info(f"laspy imported successfully from: {laspy.__file__}")
except ImportError as e:
    LASPY_AVAILABLE = False
    logger.warning(f"laspy import failed: {e}")
    logger.warning("laspy not installed, Year dimension will not be added to LiDAR data")


def add_year_to_laz(input_file: str, output_file: str, year: int) -> bool:
    """
    Add Year information to a LAZ file using laspy.
    
    Args:
        input_file: Path to the input LAZ file
        output_file: Path to the output LAZ file with Year information
        year: Year value to add (as integer)
        
    Returns:
        bool: True if successful, False otherwise
    """
    import os  # Ensure os is imported at the beginning of the function
    
    if not LASPY_AVAILABLE:
        logger.warning("laspy not available, Year dimension cannot be added")
        return False
    
    # Handle case where input and output are the same file
    if input_file == output_file:
        temp_output = f"{output_file}.temp.laz"
        logger.info(f"Input and output files are the same, using temporary file: {temp_output}")
        result = add_year_to_laz(input_file, temp_output, year)
        if result:
            try:
                if os.path.exists(output_file):
                    os.remove(output_file)
                os.rename(temp_output, output_file)
                return True
            except Exception as e:
                logger.error(f"Error renaming temporary file: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return False
        return False
        
    try:
        # Check if input file exists and is readable
        if not os.path.exists(input_file):
            logger.error(f"Input file does not exist: {input_file}")
            return False
            
        # Open the LAZ file
        with laspy.open(input_file) as in_file:
            las = in_file.read()
            
            # Create a new LasData object with the same header and point data
            # Create a copy of the header
            new_header = laspy.LasHeader(
                version=las.header.version,
                point_format=las.header.point_format
            )
            
            # Copy header attributes from the original
            for attr_name in dir(las.header):
                if not attr_name.startswith('_') and attr_name not in ['version', 'point_format']:
                    try:
                        attr_value = getattr(las.header, attr_name)
                        if not callable(attr_value):
                            setattr(new_header, attr_name, attr_value)
                    except:
                        pass
            
            # Create a new LasData with the copied header
            output_las = laspy.LasData(new_header)
            
            # Copy all points from the original
            for dim_name in las.point_format.dimension_names:
                try:
                    output_las[dim_name] = las[dim_name]
                except Exception as e:
                    logger.warning(f"Could not copy dimension {dim_name}: {str(e)}")
            
            # Add Year dimension if it doesn't exist
            if 'Year' not in output_las.point_format.dimension_names:
                try:
                    # Add Year as extra dimension
                    output_las.add_extra_dim(laspy.ExtraBytesParams(
                        name="Year",
                        type=np.uint16,  # Use unsigned 16-bit int for years
                        description=f"Acquisition year: {year}"
                    ))
                    # Fill the Year dimension with the year value
                    output_las.Year[:] = year
                    logger.info(f"Added Year dimension to output file")
                except Exception as e:
                    logger.warning(f"Could not add Year dimension: {str(e)}")
            
            # Add a custom VLR with year information
            vlr_data = f"Year: {year}".encode('utf-8')
            
            # Create a custom VLR
            vlr = laspy.vlrs.VLR(
                user_id="USGS_LiDAR_CLI",
                record_id=1,  # Custom record ID for Year
                description=f"Acquisition Year: {year}",
                record_data=vlr_data
            )
            
            # Copy existing VLRs and add the new one
            for existing_vlr in las.vlrs:
                output_las.vlrs.append(existing_vlr)
            output_las.vlrs.append(vlr)
            
            # Ensure the output directory exists
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # Write the modified file
            output_las.write(output_file)
            
            # Verify the file was created
            if not os.path.exists(output_file):
                logger.error(f"Failed to create output file: {output_file}")
                return False
                
            logger.info(f"Added Year {year} as VLR to file")
            return True
            
    except Exception as e:
        logger.error(f"Error adding Year to LAZ file: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


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
                        resolution: Optional[Union[float, str]] = None,
                        classify_ground: bool = False,
                        coordinate_reference_system: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a PDAL pipeline definition for processing EPT data.
    
    Args:
        input_url: URL to the EPT dataset
        output_laz: Path to the output LAZ file
        boundary_geojson: Optional GeoJSON boundary to limit processing
        bounds: Optional bounds to limit processing [minx, miny, maxx, maxy]
        resolution: Optional resolution parameter for EPT data. Use 'full' for native resolution (all points), 
               or a numeric value in coordinate units (meters) to control point spacing. Lower values 
               create denser point clouds with more detail but larger files.
        classify_ground: Whether to apply SMRF ground classification
        
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
    
    # Build the pipeline stages
    pipeline_stages = [reader]
    
    # Add reprojection filter if coordinate reference system is specified
    if coordinate_reference_system:
        # Check if it's a valid EPSG code format (just simple validation)
        if coordinate_reference_system.isdigit() or (coordinate_reference_system.startswith("EPSG:") and coordinate_reference_system[5:].isdigit()):
            # Format the out_srs parameter
            out_srs = coordinate_reference_system
            if not out_srs.startswith("EPSG:"):
                out_srs = f"EPSG:{out_srs}"
                
            # Add the reprojection filter
            reprojection_filter = {
                "type": "filters.reprojection",
                "out_srs": out_srs
            }
            pipeline_stages.append(reprojection_filter)
            logger.info(f"Added reprojection filter to {out_srs}")
        else:
            logger.warning(f"Invalid coordinate reference system format: {coordinate_reference_system}. Should be an EPSG code (e.g., '32615' or 'EPSG:32615').")
    
    # Add SMRF ground classification if requested
    if classify_ground:
        smrf_filter = {
            "type": "filters.smrf",
            "window": 18.0,
            "slope": 0.15,
            "threshold": 0.5,
            "ignore": "Classification[7:7]",
            "returns": "last, only"
        }
        pipeline_stages.append(smrf_filter)
        
        # Add a range filter to properly assign classification values
        range_filter = {
            "type": "filters.range",
            "limits": "Classification[2:2]"
        }
        pipeline_stages.append(range_filter)
    
    # Add writer as the final stage
    writer = {
        "type": "writers.las",
        "filename": output_laz,
        "minor_version": 4,
        "dataformat_id": 8
    }
    pipeline_stages.append(writer)
    
    # Create the pipeline
    pipeline = {
        "pipeline": pipeline_stages
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


def get_bounds(laz_file: str) -> Optional[List[float]]:
    """
    Get the bounds of a LAZ file using PDAL info.
    
    Args:
        laz_file: Path to the LAZ file
        
    Returns:
        list: [minx, miny, maxx, maxy] if successful, None otherwise
    """
    try:
        if not os.path.exists(laz_file):
            return None
            
        cmd = ["pdal", "info", "--summary", laz_file]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        if result.returncode == 0:
            # Parse the JSON output to get bounds
            summary = json.loads(result.stdout)
            if 'summary' in summary and 'bounds' in summary['summary']:
                bounds = summary['summary']['bounds']
                if all(k in bounds for k in ['minx', 'miny', 'maxx', 'maxy']):
                    return [
                        bounds['minx'], bounds['miny'],
                        bounds['maxx'], bounds['maxy']
                    ]
        
        return None
    except Exception as e:
        logger.warning(f"Error getting bounds from {laz_file}: {str(e)}")
        return None


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
        
        # Check if ground classification is enabled
        classify_ground = config.get('classify_ground', False)
        
        # Get coordinate reference system from config if specified
        coordinate_reference_system = config.get('coordinate_reference_system')
        if coordinate_reference_system:
            logger.info(f"Using coordinate reference system: {coordinate_reference_system}")
            
        # Create pipeline using the boundary directly
        pipeline = create_pdal_pipeline(
            input_url=ept_url,
            output_laz=output_file,
            boundary_geojson=boundary_geojson,
            resolution=resolution,
            classify_ground=classify_ground,
            coordinate_reference_system=coordinate_reference_system
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
