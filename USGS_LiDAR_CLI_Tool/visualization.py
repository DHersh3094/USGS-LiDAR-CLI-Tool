#!/usr/bin/env python3
"""
USGS LiDAR Visualization Module

This module handles visualization of USGS LiDAR dataset coverage
and boundary information.
"""

import os
import logging
import pandas as pd
import matplotlib.pyplot as plt
import geopandas as gpd
import contextily as cx
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from shapely.geometry import shape
from shapely.ops import unary_union
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

def create_coverage_map(boundary_geojson: Dict[str, Any], 
                       datasets: List[Dict[str, Any]], 
                       output_path: str,
                       downloaded_datasets: Optional[List[str]] = None) -> bool:
    """
    Create a visualization showing the input boundary and dataset coverage.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        datasets: List of dataset dictionaries with geometries
        output_path: Path to save the output visualization
        downloaded_datasets: Optional list of dataset names that were actually downloaded
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Creating coverage visualization at {output_path}")

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

        # Color and hatching configurations
        colors = ['#FF6B6B', '#4ECDC4', '#FFE66D', '#1A535C', 
                 '#F7B267', '#A06CD5', '#3BCEAC', '#BB4430']
        hatch_patterns = ['///', '\\\\\\', '...', 'xxx', '+++', '---', 'ooo', '***']
        
        # Store dataset geometries with their metadata for processing
        dataset_geometries = []
        boundary_geometry = None
        
        # Extract boundary geometry
        if boundary_gdf is not None:
            boundary_geometry = boundary_gdf.geometry.iloc[0]
        
        # If we have a list of downloaded datasets, filter the visualization to show only those
        filtered_datasets = datasets
        if downloaded_datasets:
            filtered_datasets = [d for d in datasets 
                               if d.get('name') in downloaded_datasets]
            if not filtered_datasets:
                logger.warning("No matching datasets found in the downloaded list, showing all datasets")
                filtered_datasets = datasets
        
        # Process all datasets first to prepare for plotting
        for i, dataset in enumerate(filtered_datasets):
            if 'geometry' in dataset:
                dataset_geometry = shape(dataset['geometry'])
                
                # If we have a boundary, clip the dataset to it
                if boundary_geometry is not None:
                    try:
                        # Intersect dataset with boundary to only show relevant parts
                        clipped_geometry = dataset_geometry.intersection(boundary_geometry)
                        if not clipped_geometry.is_empty:
                            dataset_geometries.append({
                                'geometry': clipped_geometry,
                                'year': dataset.get('year', 'Unknown'),
                                'name': dataset.get('name', f'Dataset {i+1}'),
                                'color': colors[i % len(colors)],
                                'hatch': hatch_patterns[i % len(hatch_patterns)]
                            })
                    except Exception as e:
                        logger.warning(f"Failed to clip dataset {dataset.get('name')}: {str(e)}")
                        # Fall back to using the original geometry
                        dataset_geometries.append({
                            'geometry': dataset_geometry,
                            'year': dataset.get('year', 'Unknown'),
                            'name': dataset.get('name', f'Dataset {i+1}'),
                            'color': colors[i % len(colors)],
                            'hatch': hatch_patterns[i % len(hatch_patterns)]
                        })
                else:
                    dataset_geometries.append({
                        'geometry': dataset_geometry,
                        'year': dataset.get('year', 'Unknown'),
                        'name': dataset.get('name', f'Dataset {i+1}'),
                        'color': colors[i % len(colors)],
                        'hatch': hatch_patterns[i % len(hatch_patterns)]
                    })
        
        # Sort by year (oldest first, so newest will be on top)
        dataset_geometries.sort(key=lambda x: x['year'] if isinstance(x['year'], int) else 0)
        
        # Plot each dataset
        for i, dataset_info in enumerate(dataset_geometries):
            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(geometry=[dataset_info['geometry']])
            
            # Set CRS to WGS84 (EPSG:4326) if not already set
            if gdf.crs is None:
                gdf.crs = "EPSG:4326"
            
            # Convert to Web Mercator
            gdf_webmerc = gdf.to_crs("EPSG:3857")
            
            # Plot with hatching pattern and semi-transparency for better overlap visualization
            color = dataset_info['color']
            hatch = dataset_info['hatch']
            year = dataset_info['year']
            if isinstance(year, int):
                year_str = str(year)
            else:
                year_str = year
            label = f"{dataset_info['name']} ({year_str})"
            
            # Plot with both color and hatch pattern
            gdf_webmerc.plot(ax=ax, color=color, alpha=0.5,
                           edgecolor='black', linewidth=1.5,
                           hatch=hatch, zorder=i+1)
            
            # Add to legend
            legend_elements.append(Patch(facecolor=color, alpha=0.5,
                                       edgecolor='black', linewidth=1.5,
                                       hatch=hatch, label=label))

        # Now plot the input boundary on top with higher z-order
        if boundary_gdf is not None:
            boundary_gdf_webmerc.plot(ax=ax, color='none', edgecolor='black', linewidth=3,
                                     zorder=len(dataset_geometries) + 10)  # Higher zorder to make sure it's on top
            
            # Add to legend elements
            legend_elements.insert(
                0, Line2D([0], [0], color='black', lw=3, label='Input Boundary'))
            
            # Set the map extent to focus on the user's boundary (with a small buffer)
            minx, miny, maxx, maxy = boundary_gdf_webmerc.total_bounds
            buffer = max((maxx - minx), (maxy - miny)) * 0.1  # 10% buffer
            ax.set_xlim(minx - buffer, maxx + buffer)
            ax.set_ylim(miny - buffer, maxy + buffer)
            
            # Add OpenStreetMap basemap with controlled zoom level
            cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zoom=15, attribution_size=8)

        # Add the legend with all elements
        ax.legend(handles=legend_elements, loc='best', fontsize=10,
                 title="Data Sources", title_fontsize=12)

        # Add title and clean styling
        plt.title('USGS LiDAR Coverage for Input Boundary', fontsize=16)
        # Remove axis labels
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
        return True

    except Exception as e:
        logger.error(f"Error creating visualization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def create_dataset_overlap_map(boundary_geojson: Dict[str, Any],
                              datasets: List[Dict[str, Any]],
                              output_path: str,
                              downloaded_datasets: Optional[List[str]] = None) -> bool:
    """
    Create a visualization showing areas where multiple datasets overlap.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        datasets: List of dataset dictionaries with geometries
        output_path: Path to save the output visualization
        downloaded_datasets: Optional list of dataset names that were actually downloaded
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Creating overlap visualization at {output_path}")

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

        # If we have a list of downloaded datasets, filter the visualization to show only those
        filtered_datasets = datasets
        if downloaded_datasets:
            filtered_datasets = [d for d in datasets 
                               if d.get('name') in downloaded_datasets]
            if not filtered_datasets:
                logger.warning("No matching datasets found in the downloaded list, showing all datasets")
                filtered_datasets = datasets

        # Convert datasets to GeoDataFrames
        datasets_geometries = []
        for dataset in filtered_datasets:
            if 'geometry' in dataset:
                geom = shape(dataset['geometry'])
                name = dataset.get('name', 'Unknown')
                year = dataset.get('year', 'Unknown')
                datasets_geometries.append({
                    'geometry': geom,
                    'name': name,
                    'year': year
                })
        
        # Create a GeoDataFrame from the datasets
        if not datasets_geometries:
            logger.error("No valid dataset geometries found")
            return False
            
        gdf_datasets = gpd.GeoDataFrame(datasets_geometries, crs="EPSG:4326")
        gdf_datasets_webmerc = gdf_datasets.to_crs("EPSG:3857")
        
        # Process overlaps
        overlap_gdf = gpd.GeoDataFrame(columns=['geometry', 'count'], crs="EPSG:3857")
        
        # Calculate overlaps
        for i, row in gdf_datasets_webmerc.iterrows():
            for j, other_row in gdf_datasets_webmerc.iterrows():
                if i < j:  # Avoid duplicates and self-intersection
                    intersection = row.geometry.intersection(other_row.geometry)
                    if not intersection.is_empty:
                        new_row = gpd.GeoDataFrame({'geometry': [intersection], 'count': [2]}, 
                                                  crs="EPSG:3857")
                        overlap_gdf = pd.concat([overlap_gdf, new_row], ignore_index=True)
        
        # Visualize datasets and overlaps
        if not overlap_gdf.empty:
            # Dissolve overlaps by count
            overlap_gdf = overlap_gdf.dissolve(by='count')
            overlap_gdf = overlap_gdf.reset_index()
            
            # Plot overlaps with color intensity based on count
            overlap_gdf.plot(ax=ax, column='count', cmap='Reds', 
                           legend=True, alpha=0.7,
                           legend_kwds={'label': 'Number of overlapping datasets'})
        
        # Plot individual datasets
        for idx, dataset in enumerate(datasets_geometries):
            geom = dataset['geometry']
            name = dataset['name']
            year = dataset['year']
            
            # Create a GDF for this dataset
            dataset_gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
            dataset_gdf_webmerc = dataset_gdf.to_crs("EPSG:3857")
            
            # Plot with transparency
            dataset_gdf_webmerc.plot(ax=ax, facecolor='none', 
                                  edgecolor=f'C{idx}', linewidth=1.5,
                                  label=f"{name} ({year})")
        
        # Plot the boundary
        if boundary_gdf is not None:
            boundary_gdf_webmerc.boundary.plot(ax=ax, color='black', linewidth=2, 
                                           zorder=100, label='Input Boundary')
            
            # Set the map extent
            minx, miny, maxx, maxy = boundary_gdf_webmerc.total_bounds
            buffer = max((maxx - minx), (maxy - miny)) * 0.1
            ax.set_xlim(minx - buffer, maxx + buffer)
            ax.set_ylim(miny - buffer, maxy + buffer)
        
        # Add basemap
        cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zoom=15)
        
        # Add legend
        ax.legend(loc='best')
        
        # Add title and styling
        plt.title('USGS LiDAR Dataset Overlap Areas', fontsize=16)
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.grid(True, linestyle='--', alpha=0.5)
        
        # Save the figure
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Overlap visualization saved to {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating overlap visualization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def verify_dataset_coverage(boundary_geojson: Dict[str, Any], 
                          datasets: List[Dict[str, Any]],
                          downloaded_datasets: List[str]) -> Dict[str, Any]:
    """
    Analyze dataset coverage and verify which portions of the boundary are covered.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        datasets: List of dataset dictionaries with geometries
        downloaded_datasets: List of dataset names that were actually downloaded
        
    Returns:
        dict: Coverage statistics and information
    """
    try:
        # Extract boundary geometry
        boundary_geometry = None
        if boundary_geojson.get('type') == 'FeatureCollection':
            if boundary_geojson.get('features') and len(boundary_geojson['features']) > 0:
                boundary_geometry = shape(boundary_geojson['features'][0].get('geometry'))
        elif boundary_geojson.get('type') == 'Feature':
            boundary_geometry = shape(boundary_geojson.get('geometry'))
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon']:
            boundary_geometry = shape(boundary_geojson)
            
        if not boundary_geometry:
            logger.error("Could not extract boundary geometry for coverage verification")
            return {
                "status": "error",
                "message": "Could not extract boundary geometry"
            }
            
        boundary_area = boundary_geometry.area
        
        # Filter datasets to those that were downloaded
        available_datasets = []
        for dataset in datasets:
            if dataset.get('name') in downloaded_datasets:
                available_datasets.append(dataset)
        
        if not available_datasets:
            logger.warning("No downloaded datasets found for coverage verification")
            return {
                "status": "warning",
                "message": "No downloaded datasets found",
                "coverage_percent": 0.0
            }
        
        # Calculate combined coverage of all downloaded datasets
        combined_geometry = None
        dataset_coverages = []
        
        for dataset in available_datasets:
            if 'geometry' in dataset:
                dataset_geom = shape(dataset['geometry'])
                
                # Calculate intersection with boundary
                intersection = dataset_geom.intersection(boundary_geometry)
                
                if not intersection.is_empty:
                    # Add to combined geometry
                    if combined_geometry is None:
                        combined_geometry = intersection
                    else:
                        combined_geometry = combined_geometry.union(intersection)
                    
                    # Calculate individual coverage
                    coverage_percent = (intersection.area / boundary_area) * 100
                    dataset_coverages.append({
                        "name": dataset.get('name'),
                        "year": dataset.get('year', 'Unknown'),
                        "coverage_percent": coverage_percent
                    })
        
        # Calculate total coverage
        total_coverage_percent = 0
        if combined_geometry:
            total_coverage_percent = (combined_geometry.area / boundary_area) * 100
        
        # Return coverage statistics
        return {
            "status": "success",
            "total_coverage_percent": total_coverage_percent,
            "dataset_coverages": dataset_coverages,
            "datasets_used": len(available_datasets)
        }
        
    except Exception as e:
        logger.error(f"Error verifying dataset coverage: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error verifying coverage: {str(e)}"
        }
