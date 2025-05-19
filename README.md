# USGS LiDAR CLI Tool

A command-line interface tool for downloading USGS LiDAR data based on GeoJSON boundaries.

## Data Source
Data is accessed via the Registry of open data on AWS. For more details and information on how to cite see the [USGS 3DEP LiDAR Point Clouds](https://registry.opendata.aws/usgs-lidar/)

## Features

- Download LiDAR data from USGS 3DEP datasets using GeoJSON boundary files
- Automatically identify intersecting USGS LiDAR datasets
- Create visualizations with basemaps showing data coverage and overlaps
- Support for prioritizing the most recent datasets
- Dry-run mode to check for available data without downloading

## Coverage
- Coverage is based on the USGS public lidar boundaries at: https://raw.githubusercontent.com/hobu/usgs-lidar/master/boundaries/resources.geojson
- Some areas have no coverage. See `usgs_lidar_boundaries.gpkg`

## Installation

### Prerequisites

- Python 3.7 or higher
- PDAL (Point Data Abstraction Library) installed and available in PATH

### Install from source

The easiest way to install is to use the provided installation script:

```bash
# Clone the repository
git clone https://github.com/DHersh3094/USGS-LiDAR-CLI-Tool.git
cd USGS-LiDAR-CLI-Tool

# Run the installation script
bash install_and_test.sh
```

This script will:
1. Create a virtual environment
2. Install the package and its dependencies
3. Create global command links for easier access
4. Run basic tests to verify the installation

Alternatively, you can install manually:

```bash
# Clone the repository
git clone https://github.com/DHersh3094/USGS-LiDAR-CLI-Tool.git
cd USGS-LiDAR-CLI-Tool

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate

# Install the package
pip install -e .

# Create command links (optional)
mkdir -p ~/.local/bin
ln -sf "$(pwd)/venv/bin/USGS-LiDAR-CLI-Tool" ~/.local/bin/USGS-LiDAR-CLI-Tool
ln -sf "$(pwd)/venv/bin/USGS_LiDAR_CLI_Tool" ~/.local/bin/USGS_LiDAR_CLI_Tool
```

After installation, you may need to run `source ~/.bashrc` to update your current shell, or open a new terminal window.

## Usage

### Command Line Options

- `--geojson`, `-g`: Path to input GeoJSON file defining the boundary (required)
- `--output-dir`, `-o`: Output directory for downloaded LAZ files (default: lidar_data)
- `--dry-run`, `-d`: Find intersecting datasets but don't download files
- `--resolution`, `-r`: Resolution to use for the data in Entwine Point Tile (EPT) format. Use 'full' for native resolution (all points), or specify a numeric value in coordinate units (meters) to control point spacing. For example, 1.0 will retrieve points with ~1m spacing, 0.5 creates denser point clouds, and 2.0 creates sparser data. Lower values = more detail and larger files. (default: 'full')
- `--coordinate-reference-system`, `-crs`: EPSG code to reproject laz files during download
- `--classify-ground`: Add smrf ground classification (default: true)
- `--outlier-filter`: Apply statistical outlier filter to point clouds during download removing noise points from the output. 
For more details, see the [PDAL filters.outlier documentation](https://pdal.io/en/stable/stages/filters.outlier.html#filters-outlier).
- `--outlier-mean-k`: Number of nearest neighbors to consider for outlier filter (default: 12)
- `--outlier-multiplier`: Standard deviation multiplier threshold for outlier filter (default: 2.2)
- `--verbose`, `-v`: Enable verbose logging
- `--most-recent`: Use only the most recent data when multiple datasets overlap
- `--no-visualization`: Skip creating visualization of datasets and boundary

### Examples

Check available datasets without downloading:
```bash
USGS-LiDAR-CLI-Tool --geojson demo.geojson --dry-run
```

Creates an image:
![Demo Coverage](images/demo_coverage.png)


Then download all intersecting pointclouds (in this case only 1) with a target CRS and an outlier filter:
```bash
USGS-LiDAR-CLI-Tool --geojson demo.geojson \
--coordinate-reference-system 32617 \
--outlier-filter
```

Logs are saved to `demo_info.txt`
```
USGS LiDAR Downloader Report
Generated on: 2025-05-18 11:37:24
Input GeoJSON: demo.geojson

Intersecting Datasets (1):
  1. PA_WesternPA_2_2019 (2019.0)

Download Strategy: All intersecting datasets

Download Log:
  - Successfully downloaded 1 files from PA_WesternPA_2_2019
    Output file: demo_PA_WesternPA_2_2019.laz

Each dataset was downloaded to a separate file.
```

A copy of the PDAL pipeline is also saved as `demo_PA_WesternPA_2_2019_pipeline.json`:

```json
{
    "pipeline": [
        {
            "type": "readers.ept",
            "filename": "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/PA_WesternPA_2_2019/ept.json",
            "polygon": "{\"coordinates\": [[[-80.00830228623919, 40.44337798148942], [-80.01436057451653, 40.4419411606153], [-80.01031232296975, 40.43973940536199], [-80.00837742779959, 40.44184108239551], [-80.00830228623919, 40.44337798148942]]], \"type\": \"Polygon\"}"
        },
        {
            "type": "filters.reprojection",
            "out_srs": "EPSG:32617"
        },
        {
            "type": "filters.outlier",
            "method": "statistical",
            "mean_k": 12,
            "multiplier": 2.2
        },
        {
            "type": "filters.range",
            "limits": "Classification![7:7]"
        },
        {
            "type": "writers.las",
            "filename": "lidar_data/demo/demo_PA_WesternPA_2_2019.laz",
            "minor_version": 4,
            "dataformat_id": 8
        }
    ]
}
```

## Output

The tool creates an organized directory structure:
- Each GeoJSON input gets its own subfolder
- Visualizations show dataset coverage
- Detailed info.txt file with dataset information
- Copy of the PDAL pipeline
- LAZ files are named after the input GeoJSON

## Known Issues and Bugs

### Date Parsing Issues

- **Dataset Year Parsing**: Some USGS dataset bucket names have non-standard formatting that prevents correct date/year extraction. For example, buckets like "AR_NorthEast_1_D22" will not have their dates parsed correctly, which can impact the `--most-recent` functionality and visualization year labels.

## To do:
- Add bulk download support using an input GeoPackage
- Add other PDAL commands to pipeline
- Colorization based on best matching NAIP imagery

## License

GPL 3-Clause. See [LICENSE](LICENSE) file for details.
