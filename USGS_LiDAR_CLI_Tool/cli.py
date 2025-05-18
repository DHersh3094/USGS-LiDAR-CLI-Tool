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
from .download import download_lidar_data, get_point_count
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
        help="Download only from the most recent dataset that intersects with the boundary. "
             "Older datasets are completely ignored regardless of coverage percentage."
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
    parser.add_argument(
        "--outlier-filter", action="store_true",
        help="Apply statistical outlier filter to point clouds during download"
    )
    parser.add_argument(
        "--outlier-mean-k", type=int, default=12,
        help="Number of nearest neighbors to consider for outlier filter (default: 12)"
    )
    parser.add_argument(
        "--outlier-multiplier", type=float, default=2.2,
        help="Standard deviation multiplier threshold for outlier filter (default: 2.2)"
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
        if args.outlier_filter:
            config["outlier_filter"] = True
        if args.outlier_mean_k:
            config["outlier_mean_k"] = args.outlier_mean_k
        if args.outlier_multiplier:
            config["outlier_multiplier"] = args.outlier_multiplier
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
                    
                # Add warning about coverage when using most-recent flag
                if args.most_recent and datasets:
                    logger.warning("NOTE: The visualization shows the geometric boundary of the dataset, but the")
                    logger.warning("      actual download may provide only partial coverage within that boundary.")
                    logger.warning("      This occurs because some areas within the dataset boundary may not have")
                    logger.warning("      point cloud data available in the EPT source.")
        
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
        
        # If most-recent flag is set, download only the most recent dataset
        if args.most_recent and datasets:
            # Get only the most recent dataset (datasets are already sorted by year, most recent first)
            dataset = datasets[0]
            dataset_name = dataset['name']
            dataset_year = dataset.get('year', 'Unknown year')
            
            # Log what we're doing
            log_msg = f"Using only the most recent dataset: {dataset_name} ({dataset_year})"
            logger.info(log_msg)
            info_content.append(f"  - {log_msg}")
            
            # Create output directory for this dataset
            dataset_dir = output_dir
            
            # Create a unique filename for this dataset that includes the dataset name
            unique_filename = f"{geojson_filename}_{dataset_name}"
            
            # Download data for this dataset
            logger.info(f"Downloading data from {dataset_name}")
            files = download_lidar_data(
                boundary_geojson=boundary_geojson,
                dataset=dataset,
                output_dir=str(dataset_dir),
                config=config,
                geojson_filename=unique_filename
            )
            
            if files:
                downloaded_files.extend(files)
                
                # Log success
                log_msg = f"Successfully downloaded {len(files)} files from {dataset_name}"
                logger.info(log_msg)
                info_content.append(f"  - {log_msg}")
                info_content.append(f"    Output file: {unique_filename}.laz")
            else:
                log_msg = f"No data downloaded from {dataset_name}"
                logger.warning(log_msg)
                info_content.append(f"  - {log_msg}")
            
            # Add data source information
            info_content.append(f"")
            info_content.append(f"Data Source:")
            info_content.append(f"  - {dataset_name}: {len(files) if files else 0} files")
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
        
        # When using --most-recent, no merging is needed - we only downloaded from one dataset
        
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
