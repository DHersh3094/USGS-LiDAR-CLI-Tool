#!/usr/bin/env python3
"""Setup script for USGS LiDAR CLI Tool."""

from setuptools import setup, find_packages

setup(
    name="USGS-LiDAR-CLI-Tool",
    version="0.1.0",
    author="David Hersh",
    author_email="dhersh3094@gmail.com",
    description="A command-line tool for downloading USGS LiDAR data based on GeoJSON boundaries",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/DHersh3094/USGS-LiDAR-CLI-Tool",
    packages=find_packages(include=['.', 'USGS_LiDAR_CLI_Tool*']),
    install_requires=[
        "geopandas",
        "shapely",
        "requests",
        "contextily",
        "matplotlib",
    ],
    python_requires='>=3.7',
    entry_points={
        'console_scripts': [
            'USGS-LiDAR-CLI-Tool=USGS_LiDAR_CLI_Tool.cli:main',
            'USGS_LiDAR_CLI_Tool=USGS_LiDAR_CLI_Tool.cli:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
    ],
)
