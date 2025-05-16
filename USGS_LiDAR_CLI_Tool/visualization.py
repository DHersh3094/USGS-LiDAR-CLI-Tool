#!/usr/bin/env python3
"""
USGS LiDAR Visualization Module

This module provides functions for visualizing LiDAR data and coverage
maps using contextily for adding basemaps.
"""

import logging
import os
import matplotlib.pyplot as plt
import geopandas as gpd
import contextily as ctx
from shapely.geometry import shape
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

def create_coverage_map(boundary_geojson: Dict[str, Any], 
                       datasets: List[Dict[str, Any]], 
                       output_path: str) -> bool:
    """
    Create a visualization showing the input boundary and dataset coverage.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        datasets: List of dataset dictionaries with geometries
        output_path: Path to save the output visualization
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Convert boundary to GeoDataFrame
        boundary_geom = None
        if boundary_geojson.get('type') == 'FeatureCollection':
            if boundary_geojson.get('features') and len(boundary_geojson['features']) > 0:
                boundary_geom = shape(boundary_geojson['features'][0].get('geometry'))
        elif boundary_geojson.get('type') == 'Feature':
            boundary_geom = shape(boundary_geojson.get('geometry'))
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon']:
            boundary_geom = shape(boundary_geojson)
            
        if not boundary_geom:
            logger.error("Could not extract boundary geometry for visualization")
            return False
            
        boundary_gdf = gpd.GeoDataFrame({'geometry': [boundary_geom]}, crs="EPSG:4326")
        
        # Create dataset GeoDataFrame
        dataset_geoms = []
        dataset_names = []
        dataset_years = []
        
        for dataset in datasets:
            if 'geometry' in dataset:
                geom = shape(dataset['geometry'])
                name = dataset.get('name', 'Unknown')
                year = dataset.get('year', 'N/A')
                
                dataset_geoms.append(geom)
                dataset_names.append(name)
                if year == 'N/A' or year is None:
                    dataset_years.append('Unknown year')
                else:
                    dataset_years.append(str(year))
        
        if not dataset_geoms:
            logger.error("No dataset geometries available for visualization")
            return False
            
        datasets_gdf = gpd.GeoDataFrame({
            'geometry': dataset_geoms,
            'name': dataset_names,
            'year': dataset_years
        }, crs="EPSG:4326")
        
        # Convert to Web Mercator for basemap compatibility
        boundary_gdf_web = boundary_gdf.to_crs(epsg=3857)
        datasets_gdf_web = datasets_gdf.to_crs(epsg=3857)
        
        # Create the figure and axis
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Plot datasets with different colors
        datasets_gdf_web.plot(ax=ax, alpha=0.5, column='name', cmap='Set3', 
                             legend=True, legend_kwds={'title': 'Datasets'})
        
        # Plot boundary outline
        boundary_gdf_web.boundary.plot(ax=ax, color='black', linewidth=2, linestyle='-')
        
        # Add basemap using contextily
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom=10)
        
        # Add title and labels
        ax.set_title('USGS LiDAR Dataset Coverage', fontsize=16)
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        
        # Add legend for the boundary
        from matplotlib.lines import Line2D
        legend_elements = [Line2D([0], [0], color='black', lw=2, label='Input Boundary')]
        ax.legend(handles=legend_elements, loc='lower right')
        
        # Add dataset metadata as text
        plt.figtext(0.1, 0.02, f"Datasets ({len(datasets)}):", fontsize=10, ha='left')
        for i, (name, year) in enumerate(zip(dataset_names, dataset_years)):
            plt.figtext(0.15, 0.02 - 0.02*(i+1), f"{name} ({year})", fontsize=9, ha='left')
            if i >= 4:  # Limit the number of datasets displayed
                plt.figtext(0.15, 0.02 - 0.02*(i+2), "...", fontsize=9, ha='left')
                break
                
        # Save the figure
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Created visualization at {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating visualization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def create_dataset_overlap_map(boundary_geojson: Dict[str, Any],
                              datasets: List[Dict[str, Any]],
                              output_path: str) -> bool:
    """
    Create a visualization showing areas where multiple datasets overlap.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        datasets: List of dataset dictionaries with geometries
        output_path: Path to save the output visualization
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Convert boundary to GeoDataFrame
        boundary_geom = None
        if boundary_geojson.get('type') == 'FeatureCollection':
            if boundary_geojson.get('features') and len(boundary_geojson['features']) > 0:
                boundary_geom = shape(boundary_geojson['features'][0].get('geometry'))
        elif boundary_geojson.get('type') == 'Feature':
            boundary_geom = shape(boundary_geojson.get('geometry'))
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon']:
            boundary_geom = shape(boundary_geojson)
            
        if not boundary_geom:
            logger.error("Could not extract boundary geometry for visualization")
            return False
            
        boundary_gdf = gpd.GeoDataFrame({'geometry': [boundary_geom]}, crs="EPSG:4326")
        
        # Create dataset GeoDataFrame
        dataset_geoms = []
        dataset_names = []
        
        for dataset in datasets:
            if 'geometry' in dataset:
                geom = shape(dataset['geometry'])
                name = dataset.get('name', 'Unknown')
                
                dataset_geoms.append(geom)
                dataset_names.append(name)
        
        if not dataset_geoms:
            logger.error("No dataset geometries available for visualization")
            return False
            
        datasets_gdf = gpd.GeoDataFrame({
            'geometry': dataset_geoms,
            'name': dataset_names
        }, crs="EPSG:4326")
        
        # Convert to Web Mercator for basemap compatibility
        boundary_gdf_web = boundary_gdf.to_crs(epsg=3857)
        datasets_gdf_web = datasets_gdf.to_crs(epsg=3857)
        
        # Create the figure and axis
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Create a union of all dataset geometries
        all_union = datasets_gdf_web.unary_union
        
        # Create an overlap counter
        overlap_gdf = gpd.GeoDataFrame(crs=datasets_gdf_web.crs)
        
        # Count overlaps
        for i, row in datasets_gdf_web.iterrows():
            for j, other_row in datasets_gdf_web.iterrows():
                if i < j:  # Avoid duplicates
                    intersection = row.geometry.intersection(other_row.geometry)
                    if not intersection.is_empty:
                        overlap_gdf = overlap_gdf.append({
                            'geometry': intersection,
                            'count': 2  # Start with 2 overlapping datasets
                        }, ignore_index=True)
        
        # Merge overlaps
        if not overlap_gdf.empty:
            # Dissolve by count
            overlap_gdf = overlap_gdf.dissolve(by='count', aggfunc='sum')
            overlap_gdf = overlap_gdf.reset_index()
            
            # Plot overlaps with color intensity based on count
            overlap_gdf.plot(ax=ax, column='count', cmap='Reds', 
                           legend=True, alpha=0.7,
                           legend_kwds={'label': 'Number of overlapping datasets'})
        
        # Plot datasets with different colors but with transparency
        datasets_gdf_web.plot(ax=ax, alpha=0.3, edgecolor='black', 
                             linewidth=1, facecolor='none')
        
        # Plot boundary outline
        boundary_gdf_web.boundary.plot(ax=ax, color='black', linewidth=2, linestyle='-')
        
        # Add basemap using contextily
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom=10)
        
        # Add title and labels
        ax.set_title('USGS LiDAR Dataset Overlap Areas', fontsize=16)
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        
        # Add legend for the boundary
        from matplotlib.lines import Line2D
        legend_elements = [Line2D([0], [0], color='black', lw=2, label='Input Boundary')]
        ax.legend(handles=legend_elements, loc='lower right')
        
        # Save the figure
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Created overlap visualization at {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating overlap visualization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
