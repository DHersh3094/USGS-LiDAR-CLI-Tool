#!/usr/bin/env python3
"""
USGS LiDAR Boundaries Module

This module handles finding USGS LiDAR datasets that intersect with a GeoJSON boundary.
"""

import os
import re
import json
import logging
import tempfile
import requests
import geopandas as gpd
from shapely.geometry import shape, mapping
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# URL to the USGS LiDAR GeoJSON file
USGS_LIDAR_BOUNDARIES_URL = "https://raw.githubusercontent.com/hobu/usgs-lidar/master/boundaries/resources.geojson"


def extract_year(name: str) -> Optional[int]:
    """
    Extract the year from a dataset name.
    
    Args:
        name: Dataset name string
        
    Returns:
        int: Extracted year or None if no year found
    """
    # Find all 4-digit numbers that could be years (1990-2025)
    # Use a pattern that works with underscores common in dataset names
    years = re.findall(r'(?:^|[^0-9])(19[9][0-9]|20[0-2][0-9])(?:$|[^0-9])', name)
    
    if years:
        # Return the first year found as an integer
        return int(years[0])
    return None


def download_usgs_boundaries() -> Optional[Dict[str, Any]]:
    """
    Download the USGS LiDAR boundaries GeoJSON file.
    
    Returns:
        dict: Parsed GeoJSON data or None if download failed
    """
    try:
        logger.info(f"Downloading USGS LiDAR boundaries from {USGS_LIDAR_BOUNDARIES_URL}")
        response = requests.get(USGS_LIDAR_BOUNDARIES_URL)
        response.raise_for_status()
        
        # Parse JSON response
        geojson_data = response.json()
        
        # Check if it's a valid GeoJSON FeatureCollection
        if geojson_data.get('type') != 'FeatureCollection':
            logger.error("Downloaded data is not a valid GeoJSON FeatureCollection")
            return None
        
        logger.info(f"Successfully downloaded USGS LiDAR boundaries ({len(geojson_data.get('features', []))} features)")
        return geojson_data
    
    except Exception as e:
        logger.error(f"Error downloading USGS LiDAR boundaries: {str(e)}")
        return None


def boundary_to_gdf(boundary_geojson: Dict[str, Any]) -> Optional[gpd.GeoDataFrame]:
    """
    Convert a GeoJSON boundary to a GeoDataFrame.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        
    Returns:
        GeoDataFrame: Boundary as a GeoDataFrame or None if conversion failed
    """
    try:
        # Handle different GeoJSON types
        if boundary_geojson.get('type') == 'FeatureCollection':
            # If it's a FeatureCollection, use the first feature's geometry
            if not boundary_geojson.get('features'):
                logger.error("GeoJSON FeatureCollection has no features")
                return None
            
            geometry = boundary_geojson['features'][0].get('geometry')
            if not geometry:
                logger.error("First feature in FeatureCollection has no geometry")
                return None
            
            geom_obj = shape(geometry)
            
        elif boundary_geojson.get('type') == 'Feature':
            # If it's a Feature, use its geometry
            geometry = boundary_geojson.get('geometry')
            if not geometry:
                logger.error("GeoJSON Feature has no geometry")
                return None
            
            geom_obj = shape(geometry)
            
        elif boundary_geojson.get('type') in ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString', 'Point', 'MultiPoint']:
            # If it's a geometry, use it directly
            geom_obj = shape(boundary_geojson)
            
        else:
            logger.error(f"Unsupported GeoJSON type: {boundary_geojson.get('type')}")
            return None
        
        # Create a GeoDataFrame from the geometry
        gdf = gpd.GeoDataFrame({'geometry': [geom_obj]}, crs="EPSG:4326")
        return gdf
    
    except Exception as e:
        logger.error(f"Error converting boundary to GeoDataFrame: {str(e)}")
        return None


def find_intersecting_datasets(boundary_geojson: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Find USGS LiDAR datasets that intersect with the input boundary.
    
    Args:
        boundary_geojson: GeoJSON boundary as a dictionary
        
    Returns:
        list: List of dataset dictionaries with name, url, year, and geometry
    """
    # Download USGS LiDAR boundaries
    usgs_boundaries = download_usgs_boundaries()
    if not usgs_boundaries:
        logger.error("Failed to download USGS LiDAR boundaries")
        return []
    
    # Convert boundary to GeoDataFrame
    boundary_gdf = boundary_to_gdf(boundary_geojson)
    if boundary_gdf is None:
        logger.error("Failed to convert boundary to GeoDataFrame")
        return []
    
    # Create a GeoDataFrame from the USGS boundaries
    try:
        features = usgs_boundaries.get('features', [])
        if not features:
            logger.error("No features found in USGS boundaries")
            return []
        
        # Create lists for geometries and properties
        geometries = []
        properties_list = []
        
        for feature in features:
            geometry = feature.get('geometry')
            properties = feature.get('properties', {})
            
            if geometry and properties:
                # Extract year from name and add it as a property
                name = properties.get('name', '')
                if name:
                    year = extract_year(name)
                    if year:
                        properties['year'] = year
                    
                    # Add to lists
                    geometries.append(shape(geometry))
                    properties_list.append(properties)
        
        # Create a GeoDataFrame for USGS boundaries
        usgs_gdf = gpd.GeoDataFrame(
            properties_list,
            geometry=geometries,
            crs="EPSG:4326"
        )
        
        # Find intersecting datasets
        logger.info("Finding intersecting datasets")
        intersecting = usgs_gdf[usgs_gdf.intersects(boundary_gdf.iloc[0].geometry)]
        
        if len(intersecting) == 0:
            logger.info("No intersecting datasets found")
            return []
        
        # Prepare result list with dataset information
        result = []
        for _, row in intersecting.iterrows():
            dataset = {
                'name': row.get('name', ''),
                'url': row.get('url', ''),
                'geometry': mapping(row.geometry),  # Convert to GeoJSON geometry
            }
            
            # Add year if available
            if 'year' in row:
                dataset['year'] = row['year']
                
            # Add s3 url for EPT data
            if 'url' in row and row['url']:
                # Extract bucket information from the URL
                s3_url = extract_s3_bucket_from_url(row['url'])
                if s3_url:
                    dataset['s3_url'] = s3_url
            
            result.append(dataset)
        
        logger.info(f"Found {len(result)} intersecting datasets")
        return result
        
    except Exception as e:
        logger.error(f"Error finding intersecting datasets: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def extract_s3_bucket_from_url(url: str) -> Optional[str]:
    """
    Extract S3 bucket URL from the dataset URL.
    
    Args:
        url: Dataset URL
        
    Returns:
        str: S3 bucket URL or None if not found
    """
    try:
        # Check if the URL is an Amazon S3 URL
        if "amazonaws.com" in url:
            # Extract s3 path components from URLs like 
            # https://s3-us-west-2.amazonaws.com/usgs-lidar-public/AR_Dardenelle_2011/ept.json
            if "usgs-lidar-public" in url:
                parts = url.split("usgs-lidar-public/")
                if len(parts) > 1:
                    dataset_path = parts[1].split("/ept.json")[0]
                    return f"usgs-lidar-public/{dataset_path}"
            
            # Handle other patterns of USGS LiDAR URLs
            match = re.search(r'amazonaws\.com/([^/]+)/([^/]+)', url)
            if match:
                bucket = match.group(1)
                prefix = match.group(2)
                return f"{bucket}/{prefix}"
        
        return None
    except Exception as e:
        logger.error(f"Error extracting S3 bucket from URL: {str(e)}")
        return None
