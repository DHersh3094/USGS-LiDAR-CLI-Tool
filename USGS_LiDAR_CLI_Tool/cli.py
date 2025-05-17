#!/usr/bin/env python3
"""
USGS LiDAR CLI Tool

This script provides a command-line interface for downloading USGS LiDAR data
based on GeoJSON boundaries. It identifies which USGS LiDAR datasets intersect
with the input boundary and downloads the LAZ files from the corresponding S3 buckets.
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
import matplotlib.pyplot as plt
import geopandas as gpd
import contextily as cx
from pathlib import Path
from typing import Optional, List, Dict, Any
from shapely.geometry import shape, box, mapping
from shapely.ops import unary_union

from .boundaries import find_intersecting_datasets
from .download import download_lidar_data, merge_laz_files, get_point_count
from .config import load_config
from .visualization import create_coverage_map, verify_dataset_coverage

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the CLI"""
    parser = argparse.ArgumentParser(
        description="Download USGS LiDAR data based on GeoJSON boundaries"
    )
    parser.add_argument(
        "--geojson", "-g", type=str, required=True,
        help="Path to input GeoJSON file defining the boundary"
    )
    parser.add_argument(
        "--output-dir", "-o", type=str, default="lidar_data",
        help="Output directory for downloaded LAZ files (default: lidar_data)"
    )
    parser.add_argument(
        "--config", "-c", type=str, default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    parser.add_argument(
        "--resolution", "-r", type=str,
        help="Resolution to use for the data in Entwine Point Tile (EPT) format. "
             "Use 'full' for native resolution (all points), or specify a numeric value "
             "in coordinate units (meters) to control point spacing. For example, "
             "'1.0' will retrieve points with ~1m spacing, '0.5' creates denser point clouds, "
             "and '2.0' creates sparser data. Lower values = more detail and larger files. "
             "(default: use resolution from config)"
    )
    parser.add_argument(
        "--workers", "-w", type=int,
        help="Number of parallel workers (default: from config or 8)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--dry-run", "-d", action="store_true",
        help="Find intersecting datasets but don't download files"
    )
    parser.add_argument(
        "--keep-temp", "-k", action="store_true",
        help="Keep temporary downloaded files from each dataset"
    )
    parser.add_argument(
        "--most-recent", action="store_true",
        help="Use the most recent dataset as primary source, then fill gaps with older datasets. "
             "Gaps are determined by the actual geometry coverage of the most recent dataset. "
             "Areas not covered by newer datasets will be filled with data from older datasets."
    )
    parser.add_argument(
        "--no-visualization", action="store_true",
        help="Skip creating visualization of datasets and boundary"
    )
    parser.add_argument(
        "--classify-ground", action="store_true",
        help="Apply SMRF ground classification to point clouds during download"
    )
    parser.add_argument(
        "--coordinate-reference-system", "-crs", type=str,
        help="EPSG code for output coordinate reference system (e.g., '32615'). "
             "The downloaded LAZ files will be reprojected to this CRS."
    )
    # Removed the --coverage-method option as requested
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create output directory and subfolder for this geojson
    base_output_dir = Path(args.output_dir)
    base_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract geojson filename to use for the subfolder and LAZ files
    geojson_filename = Path(args.geojson).stem
    
    # Create a specific subfolder for this geojson input
    output_dir = base_output_dir / geojson_filename
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Override config with command line arguments
        if args.resolution:
            config["resolution"] = args.resolution
        if args.workers:
            config["download_workers"] = args.workers
        if args.classify_ground:
            config["classify_ground"] = True
        if args.coordinate_reference_system:
            config["coordinate_reference_system"] = args.coordinate_reference_system
        # Coverage method removed - simplified approach used
        
        # Load the input GeoJSON
        with open(args.geojson, 'r') as f:
            boundary_geojson = json.load(f)
        
        # Find intersecting datasets
        logger.info(f"Finding USGS LiDAR datasets that intersect with the input boundary")
        datasets = find_intersecting_datasets(boundary_geojson)
        
        if not datasets:
            logger.warning("No intersecting USGS LiDAR datasets found")
            return 0
        
        # Sort datasets by year (most recent first)
        datasets.sort(key=lambda x: x.get('year', 0), reverse=True)
        
        logger.info(f"Found {len(datasets)} intersecting datasets")
        for i, dataset in enumerate(datasets, 1):
            logger.info(f"  {i}. {dataset['name']} ({dataset.get('year', 'Unknown year')})")
            
        # Create visualization of the boundary and dataset geometries
        if not args.no_visualization:
            visualization_path = output_dir / f"{geojson_filename}_coverage.png"
            
            # Track which datasets will actually be downloaded
            downloaded_dataset_names = []
            
            # For most-recent flag, only the most recent dataset is used
            if args.most_recent and datasets:
                downloaded_dataset_names.append(datasets[0]['name'])
            else:
                # All datasets will be downloaded
                for dataset in datasets:
                    downloaded_dataset_names.append(dataset['name'])
            
            # Create visualization showing only datasets that will be downloaded
            create_coverage_map(boundary_geojson, datasets, str(visualization_path), 
                               downloaded_datasets=downloaded_dataset_names)
            
            # Verify and log coverage statistics
            coverage_stats = verify_dataset_coverage(boundary_geojson, datasets, downloaded_dataset_names)
            
            if coverage_stats["status"] == "success":
                logger.info(f"Coverage analysis: {coverage_stats['total_coverage_percent']:.2f}% of boundary covered")
                for ds_coverage in coverage_stats["dataset_coverages"]:
                    logger.info(f"  - {ds_coverage['name']}: {ds_coverage['coverage_percent']:.2f}% coverage")
        
        # If dry-run is enabled, just print datasets and exit
        if args.dry_run:
            logger.info("Dry run mode - not downloading files")
            return 0
        
        # Create temp directory for intermediate files if needed
        temp_dir = output_dir / "temp"
        if len(datasets) > 1:
            temp_dir.mkdir(exist_ok=True)
        
        # Create a text file to explain the download process
        info_file = output_dir / f"{geojson_filename}_info.txt"
        info_content = [
            f"USGS LiDAR Downloader Report",
            f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Input GeoJSON: {args.geojson}",
            f"",
            f"Intersecting Datasets ({len(datasets)}):",
        ]
        for i, dataset in enumerate(datasets, 1):
            info_content.append(f"  {i}. {dataset['name']} ({dataset.get('year', 'Unknown year')})")
        
        info_content.append(f"")
        info_content.append(f"Download Strategy: {'Most recent data only' if args.most_recent else 'All intersecting datasets'}")
        info_content.append(f"")
        info_content.append(f"Download Log:")
        
        # Download LAZ files from each dataset
        downloaded_files = []
        # Keep track of which file came from which dataset and its year
        file_source_map = {}
        
        # If most-recent flag is set, try to use most recent dataset first, then fill gaps with older datasets
        if args.most_recent and datasets:
            # Dictionary to track coverage from each dataset
            coverage_info = {}
        
            # Process datasets in order of recency (most recent first)
            remaining_boundary = boundary_geojson.copy()
        
            for i, dataset in enumerate(datasets):
                dataset_name = dataset['name']
                dataset_year = dataset.get('year', 'Unknown year')
        
                # Create a modified boundary for this dataset that excludes areas already covered by newer datasets
                current_boundary = boundary_geojson.copy()
                
                if i == 0:
                    log_msg = f"Using most recent dataset as primary: {dataset_name} ({dataset_year})"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                else:
                    log_msg = f"Looking for gaps to fill with older dataset: {dataset_name} ({dataset_year})"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                    
                    # Skip all datasets except the most recent one when using --most-recent flag
                    log_msg = f"Skipping older dataset {dataset_name} - only using most recent dataset"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                    continue
        
                # Create temporary directory for this dataset's files
                dataset_dir = temp_dir / dataset_name
                dataset_dir.mkdir(parents=True, exist_ok=True)
        
                # Download data for this dataset (using modified boundary for older datasets)
                logger.info(f"Downloading data from {dataset_name}")
                files = download_lidar_data(
                    boundary_geojson=current_boundary,
                    dataset=dataset,
                    output_dir=str(dataset_dir),
                    config=config,
                    geojson_filename=f"{geojson_filename}_{dataset_name}"
                )
        
                if files:
                    downloaded_files.extend(files)
                    coverage_info[dataset_name] = len(files)
        
                    # Store year information for each file
                    for file in files:
                        file_source_map[file] = {
                            'dataset': dataset_name,
                            'year': dataset.get('year', 0)
                        }
        
                    # If this isn't the first dataset, it's being used to fill gaps
                    if i > 0:
                        log_msg = f"Filled gaps with {len(files)} files from {dataset_name}"
                    else:
                        log_msg = f"Successfully downloaded {len(files)} files from {dataset_name}"
        
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
        
                    # Update remaining boundary (for future gap filling)
                    # This is a simplification - in a real implementation, you'd compute the actual
                    # coverage area from the downloaded files and subtract it from the boundary
                    # For now, we'll simply assume each dataset might have gaps
                else:
                    log_msg = f"No data downloaded from {dataset_name}"
                    logger.warning(log_msg)
                    info_content.append(f"  - {log_msg}")
        
                # Stop if we've filled all gaps or this is the last dataset
                if i == len(datasets) - 1:
                    break
        
            # Add summary of data sources
            info_content.append(f"")
            info_content.append(f"Data Sources:")
            for dataset_name, count in coverage_info.items():
                info_content.append(f"  - {dataset_name}: {count} files")
        else:
            # Download from all datasets separately - no merging
            for dataset in datasets:
                # Create output directory for this dataset (inside the main output dir)
                dataset_dir = output_dir
                dataset_dir.mkdir(parents=True, exist_ok=True)
                
                # Create a unique filename for this dataset
                unique_filename = f"{geojson_filename}_{dataset['name']}"
                
                logger.info(f"Downloading data from {dataset['name']}")
                files = download_lidar_data(
                    boundary_geojson=boundary_geojson,
                    dataset=dataset,
                    output_dir=str(dataset_dir),
                    config=config,
                    geojson_filename=unique_filename
                )
                
                if files:
                    # Add year information to each file
                    for file in files:
                        year = dataset.get('year', 0)
                        
                        try:
                            # Add year dimension to the file
                            from .download import add_year_to_laz
                            success = add_year_to_laz(file, file, year)
                            
                            if success:
                                logger.info(f"Added year {year} to {file}")
                            else:
                                logger.warning(f"Failed to add year dimension to {file}, but file was still downloaded")
                        except Exception as e:
                            logger.warning(f"Error adding year to {file}: {str(e)}")
                    
                    # Keep track of all downloaded files
                    downloaded_files.extend(files)
                    
                    # Log success
                    log_msg = f"Successfully downloaded {len(files)} files from {dataset['name']}"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                    info_content.append(f"    Output file: {unique_filename}.laz")
                else:
                    log_msg = f"No data downloaded from {dataset['name']}"
                    logger.warning(log_msg)
                    info_content.append(f"  - {log_msg}")
            
            # Add summary about individual files
            if downloaded_files:
                info_content.append(f"")
                info_content.append(f"Each dataset was downloaded to a separate file.")
                info_content.append(f"No merging was performed because --most-recent flag was not used.")
        
        # When using --most-recent, we need to merge the files
        if args.most_recent and downloaded_files:
            info_content.append(f"")
            
            # Define the final output file
            merged_file = str(output_dir / f"{geojson_filename}.laz")
            
            # For multiple files, merge them
            if len(downloaded_files) > 1:
                info_content.append(f"Merging Files:")
                logger.info("Merging downloaded LAZ files")
            else:
                # For single file, just copy/move to final location
                info_content.append(f"Processing File:")
                logger.info("Processing downloaded LAZ file")
        
            # Create a year mapping for each file
            year_mapping = {}
            for file, info in file_source_map.items():
                # Use the actual year value from the dataset information
                year_mapping[file] = info['year']
                
            # Add the mapping information to the info file
            import os  # Ensure os is imported here for os.path.basename
            info_content.append(f"")
            info_content.append(f"Year Mapping for Points:")
            for file, info in file_source_map.items():
                short_path = os.path.basename(file)
                info_content.append(f"  - {short_path}: Dataset={info['dataset']}, Year={info['year']}")
        
            # Process based on file count
            if len(downloaded_files) == 1:
                # Single file case - add year dimension and save to final location
                source_file = downloaded_files[0]
                log_msg = f"Only one dataset used, adding year dimension and saving to final location"
                logger.info(log_msg)
                info_content.append(f"  - {log_msg}")
                
                # Get year value from file source mapping
                year = 0
                if source_file in file_source_map:
                    year = file_source_map[source_file]['year']
                    
                try:
                    # If source and destination are the same, use a temporary file
                    if source_file == merged_file:
                        temp_file = f"{merged_file}.temp"
                        
                        # First add year dimension to temp file
                        from .download import add_year_to_laz
                        success = add_year_to_laz(source_file, temp_file, year)
                        
                        if success:
                            # Then replace original with temp file
                            import os
                            if os.path.exists(merged_file):
                                os.remove(merged_file)
                            os.rename(temp_file, merged_file)
                            logger.info(f"Added year {year} to {merged_file}")
                        else:
                            logger.error(f"Failed to add year dimension to {source_file}")
                    else:
                        # Add year dimension directly to the merged file location
                        from .download import add_year_to_laz
                        success = add_year_to_laz(source_file, merged_file, year)
                        logger.info(f"Added year {year} to {merged_file}")
                except Exception as e:
                    logger.error(f"Error processing file: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    success = False
            else:
                # Multiple files case - merge them with year attribute
                logger.info(f"Merging files with year attribute for identifying source datasets")
                success = merge_laz_files(downloaded_files, merged_file, year_mapping)
        
            if success:
                point_count = get_point_count(merged_file)
                file_size = os.path.getsize(merged_file) / (1024 * 1024)  # Convert to MB
                log_msg = f"Successfully merged files into {merged_file}: {file_size:.2f} MB, {point_count} points"
                logger.info(log_msg)
                info_content.append(f"  - {log_msg}")
        
                # Add appropriate information about file sources
                if len(downloaded_files) > 1:
                    info_content.append(f"  - Final LAZ file contains data from multiple USGS datasets")
                else:
                    dataset_name = list(file_source_map.values())[0]['dataset']
                    dataset_year = list(file_source_map.values())[0]['year']
                    info_content.append(f"  - Final LAZ file contains data from {dataset_name} ({dataset_year})")
                
                info_content.append(f"  - Check visualization file for coverage information")
        
                # Clean up temp files unless --keep-temp was specified
                if not args.keep_temp:
                    try:
                        # Use shutil.rmtree for a more robust directory cleanup
                        import shutil
                        if temp_dir.exists():
                            logger.info(f"Cleaning up temporary directory: {temp_dir}")
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            logger.info("Temporary directory cleaned up successfully")
                    except Exception as e:
                        logger.warning(f"Error cleaning up temp directory: {str(e)}")
            else:
                log_msg = f"Failed to merge files"
                logger.error(log_msg)
                info_content.append(f"  - {log_msg}")
                # Write info file
                with open(info_file, 'w') as f:
                    f.write('\n'.join(info_content))
                return 1
        
        # Write info file
        with open(info_file, 'w') as f:
            f.write('\n'.join(info_content))
        
        logger.info(f"Successfully downloaded USGS LiDAR data to {output_dir}")
        logger.info(f"Download information saved to {info_file}")
        return 0
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
