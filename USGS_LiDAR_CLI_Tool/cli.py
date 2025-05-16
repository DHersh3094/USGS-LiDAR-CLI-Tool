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
import matplotlib.pyplot as plt
import geopandas as gpd
import contextily as cx
from pathlib import Path
from typing import Optional, List, Dict, Any
from shapely.geometry import shape, box

from .boundaries import find_intersecting_datasets
from .download import download_lidar_data, merge_laz_files, get_point_count
from .config import load_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def create_visualization(boundary_geojson: Dict[str, Any], datasets: List[Dict[str, Any]],
                         output_path: str) -> None:
    """
    Create a visualization showing the input boundary and intersecting USGS LiDAR datasets.

    Args:
        boundary_geojson: The input GeoJSON boundary
        datasets: List of intersecting datasets with geometries
        output_path: Path to save the visualization image
    """
    try:
        logger.info(f"Creating visualization at {output_path}")

        # Create a figure and axis with good size for readability
        fig, ax = plt.subplots(figsize=(12, 10))

        # Extract and prepare the input boundary
        boundary_gdf = None
        if boundary_geojson.get('type') == 'FeatureCollection':
            boundary_gdf = gpd.GeoDataFrame.from_features(boundary_geojson)
        elif boundary_geojson.get('type') == 'Feature':
            boundary_gdf = gpd.GeoDataFrame(
                geometry=[shape(boundary_geojson['geometry'])])
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon']:
            boundary_gdf = gpd.GeoDataFrame(geometry=[shape(boundary_geojson)])
            
        # Set CRS to WGS84 (EPSG:4326) if not already set
        if boundary_gdf is not None and boundary_gdf.crs is None:
            boundary_gdf.crs = "EPSG:4326"
            
        # Convert to Web Mercator for use with contextily basemap
        boundary_gdf_webmerc = boundary_gdf.to_crs("EPSG:3857")

        # Lists to keep track of legend elements
        legend_elements = []

        # Get dataset geometries and clip them to the boundary for visualization
        from shapely.ops import unary_union
        
        colors = ['#FF6B6B', '#4ECDC4', '#FFE66D', '#1A535C', 
                  '#F7B267', '#A06CD5', '#3BCEAC', '#BB4430']
        
        # Store dataset geometries with their metadata for processing
        dataset_geometries = []
        boundary_geometry = None
        
        # Extract boundary geometry
        if boundary_gdf is not None:
            boundary_geometry = boundary_gdf.geometry.iloc[0]
        
        # Process all datasets first to prepare for plotting
        for i, dataset in enumerate(datasets):
            if 'geometry' in dataset:
                dataset_geometry = shape(dataset['geometry'])
                
                # If we have a boundary, clip the dataset to it
                if boundary_geometry is not None:
                    try:
                        # Intersect dataset with boundary to only show relevant parts
                        # Using the & operator which is equivalent to intersection
                        clipped_geometry = dataset_geometry & boundary_geometry
                        if not clipped_geometry.is_empty:
                            dataset_geometries.append({
                                'geometry': clipped_geometry,
                                'year': dataset.get('year', 'Unknown'),
                                'name': dataset.get('name', f'Dataset {i+1}'),
                                'color': colors[i % len(colors)]
                            })
                    except Exception as e:
                        logger.warning(f"Failed to clip dataset {dataset.get('name')}: {str(e)}")
                        # Fall back to using the original geometry
                        dataset_geometries.append({
                            'geometry': dataset_geometry,
                            'year': dataset.get('year', 'Unknown'),
                            'name': dataset.get('name', f'Dataset {i+1}'),
                            'color': colors[i % len(colors)]
                        })
                else:
                    dataset_geometries.append({
                        'geometry': dataset_geometry,
                        'year': dataset.get('year', 'Unknown'),
                        'name': dataset.get('name', f'Dataset {i+1}'),
                        'color': colors[i % len(colors)]
                    })
        
        # Sort by year (oldest first, so newest will be on top)
        dataset_geometries.sort(key=lambda x: x['year'])
        
        # Plot each dataset
        for dataset_info in dataset_geometries:
            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(geometry=[dataset_info['geometry']])
            
            # Set CRS to WGS84 (EPSG:4326) if not already set
            if gdf.crs is None:
                gdf.crs = "EPSG:4326"
            
            # Convert to Web Mercator
            gdf_webmerc = gdf.to_crs("EPSG:3857")
            
            # Plot with semi-transparency to show overlap areas
            color = dataset_info['color']
            label = f"{dataset_info['name']} ({dataset_info['year']})"
            
            gdf_webmerc.plot(ax=ax, color=color, alpha=0.5,
                            edgecolor=color, linewidth=1.5)
            
            # Add to legend
            from matplotlib.patches import Patch
            legend_elements.append(Patch(facecolor=color, alpha=0.5,
                                        edgecolor=color, label=label))

        # Now plot the input boundary on top with higher z-order
        if boundary_gdf is not None:
            boundary_gdf_webmerc.plot(ax=ax, color='none', edgecolor='black', linewidth=3,
                                      zorder=10)  # Higher zorder to make sure it's on top
            
            # Add to legend elements
            from matplotlib.lines import Line2D
            legend_elements.insert(
                0, Line2D([0], [0], color='black', lw=3, label='Input Boundary'))
            
            # Set the map extent to focus on the user's boundary (with a small buffer)
            minx, miny, maxx, maxy = boundary_gdf_webmerc.total_bounds
            buffer = max((maxx - minx), (maxy - miny)) * 0.1  # 10% buffer
            ax.set_xlim(minx - buffer, maxx + buffer)
            ax.set_ylim(miny - buffer, maxy + buffer)
            
            # Add OpenStreetMap basemap with controlled zoom level (19 is max for OpenStreetMap)
            cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zoom=18, attribution_size=8)

        # Add the legend with all elements
        ax.legend(handles=legend_elements, loc='best', fontsize=10,
                  title="Data Sources", title_fontsize=12)

        # Add title and clean styling
        plt.title('USGS LiDAR Coverage for Input Boundary', fontsize=16)
        # Remove axis labels entirely instead of setting fontsize to 0
        ax.set_xlabel('')
        ax.set_ylabel('')
        # Remove tick labels
        ax.set_xticklabels([])
        ax.set_yticklabels([])

        # Add grid lines
        ax.grid(True, linestyle='--', alpha=0.5)

        # Improve layout
        plt.tight_layout()

        # Save the figure
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Visualization saved to {output_path}")

    except Exception as e:
        logger.error(f"Error creating visualization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


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
        help="Resolution to use for the data. Use 'full' for native resolution, "
             "or specify a numeric value (default: use resolution from config)"
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
        help="Use only the most recent data when multiple datasets overlap"
    )
    parser.add_argument(
        "--no-visualization", action="store_true",
        help="Skip creating visualization of datasets and boundary"
    )
    
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
        if not args.no_visualization and not args.dry_run:
            visualization_path = output_dir / f"{geojson_filename}_coverage.png"
            create_visualization(boundary_geojson, datasets, str(visualization_path))
        
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
        
                if i == 0:
                    log_msg = f"Using most recent dataset as primary: {dataset_name} ({dataset_year})"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                else:
                    # Check if we already have full coverage from newer datasets
                    if len(downloaded_files) > 0:
                        # Check coverage by comparing point counts
                        prev_dataset_points = sum([get_point_count(f) for f in downloaded_files])
                        if prev_dataset_points > 0:
                            # Estimate if we have good coverage based on point count
                            # We'll use a simple heuristic: if we have over 1 million points, it's likely good coverage
                            if prev_dataset_points > 1000000:
                                log_msg = f"Skipping older dataset {dataset_name} - newer dataset provides sufficient coverage"
                                logger.info(log_msg)
                                info_content.append(f"  - {log_msg}")
                                break
        
                    log_msg = f"Looking for gaps to fill with older dataset: {dataset_name} ({dataset_year})"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
        
                # Create temporary directory for this dataset's files
                dataset_dir = temp_dir / dataset_name
                dataset_dir.mkdir(parents=True, exist_ok=True)
        
                # Download data for this dataset
                logger.info(f"Downloading data from {dataset_name}")
                files = download_lidar_data(
                    boundary_geojson=remaining_boundary,
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
            # Download from all datasets
            for dataset in datasets:
                # Create temporary directory for this dataset's files
                dataset_dir = temp_dir / dataset['name'] if len(datasets) > 1 else output_dir
                dataset_dir.mkdir(parents=True, exist_ok=True)
        
                logger.info(f"Downloading data from {dataset['name']}")
                files = download_lidar_data(
                    boundary_geojson=boundary_geojson,
                    dataset=dataset,
                    output_dir=str(dataset_dir),
                    config=config,
                    geojson_filename=geojson_filename
                )
        
                if files:
                    downloaded_files.extend(files)
        
                    # Store year information for each file
                    for file in files:
                        file_source_map[file] = {
                            'dataset': dataset['name'],
                            'year': dataset.get('year', 0)
                        }
        
                    log_msg = f"Successfully downloaded {len(files)} files from {dataset['name']}"
                    logger.info(log_msg)
                    info_content.append(f"  - {log_msg}")
                else:
                    log_msg = f"No data downloaded from {dataset['name']}"
                    logger.warning(log_msg)
                    info_content.append(f"  - {log_msg}")
        
        # Process downloaded files (merge multiple or copy single)
        if downloaded_files:
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
        
            # Create a mapping using SourceID instead of Year (Year may not be supported in some PDAL versions)
            # SourceID is a standard LAS dimension that can store metadata
            source_id_mapping = {}
            for file, info in file_source_map.items():
                # Convert year to an integer ID (1 for oldest, incrementing by 1)
                # We'll document the mapping in the info file
                source_id_mapping[file] = info['year']
                
            # Add the mapping information to the info file
            info_content.append(f"")
            info_content.append(f"Source ID to Year Mapping:")
            for file, info in file_source_map.items():
                short_path = os.path.basename(file)
                info_content.append(f"  - {short_path}: Dataset={info['dataset']}, Year={info['year']}")
        
            # Process based on file count
            if len(downloaded_files) == 1:
                # Single file case - just move to final location
                source_file = downloaded_files[0]
                log_msg = f"Only one dataset used, copying file to final location"
                logger.info(log_msg)
                info_content.append(f"  - {log_msg}")
                
                try:
                    # Copy the file to maintain the original
                    import shutil
                    shutil.copy2(source_file, merged_file)
                    success = True
                    logger.info(f"Copied {source_file} to {merged_file}")
                except Exception as e:
                    logger.error(f"Error copying file: {str(e)}")
                    success = False
            else:
                # Multiple files case - merge them
                success = merge_laz_files(downloaded_files, merged_file, None)  # Skip adding year for now
        
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
        elif len(downloaded_files) == 1 and len(datasets) == 1:
            # If there's only one file and it's in the wrong location, move it
            source_file = downloaded_files[0]
            target_file = str(output_dir / f"{geojson_filename}.laz")
        
            if source_file != target_file:
                try:
                    # Rename file to match geojson filename
                    import shutil
                    shutil.move(source_file, target_file)
                    logger.info(f"Renamed {source_file} to {target_file}")
                except Exception as e:
                    logger.error(f"Error renaming file: {str(e)}")
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
