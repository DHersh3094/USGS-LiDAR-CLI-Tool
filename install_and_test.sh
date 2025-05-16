#!/bin/bash
#!/bin/bash
# Installation and test script for USGS LiDAR CLI Tool

# Exit on error
set -e

echo "========== Creating a virtual environment =========="
python3 -m venv venv
source venv/bin/activate

echo "========== Installing the package locally =========="
pip install --upgrade pip
pip install -e .

echo "========== Installing laspy with lazrs backend =========="
pip install laspy lazrs

echo "========== Checking installation =========="
which USGS-LiDAR-CLI-Tool || echo "Command not found. Installation may have failed."

echo "========== Verifying dependencies =========="
pip show contextily || echo "Contextily is not installed!"
pip show geopandas || echo "GeoPandas is not installed!"
pip show shapely || echo "Shapely is not installed!"
pip show requests || echo "Requests is not installed!"
pip show matplotlib || echo "Matplotlib is not installed!"

echo "========== Testing CLI help =========="
USGS-LiDAR-CLI-Tool --help

echo "========== Installing global commands =========="
# Create the user's bin directory if it doesn't exist
mkdir -p ~/.local/bin

# Create wrapper scripts that activate the virtual environment
cat > ~/.local/bin/USGS-LiDAR-CLI-Tool << EOF
#!/bin/bash
source "$(pwd)/venv/bin/activate"
"$(pwd)/venv/bin/USGS-LiDAR-CLI-Tool" "\$@"
EOF

cat > ~/.local/bin/USGS_LiDAR_CLI_Tool << EOF
#!/bin/bash
source "$(pwd)/venv/bin/activate"
"$(pwd)/venv/bin/USGS_LiDAR_CLI_Tool" "\$@"
EOF

# Make the wrapper scripts executable
chmod +x ~/.local/bin/USGS-LiDAR-CLI-Tool
chmod +x ~/.local/bin/USGS_LiDAR_CLI_Tool

# Add ~/.local/bin to PATH if it's not already there
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  echo "Added ~/.local/bin to PATH in ~/.bashrc"
  echo "Please run 'source ~/.bashrc' or open a new terminal to update your PATH"
fi

echo "========== Installation and test complete =========="
echo "You can now run: USGS-LiDAR-CLI-Tool --geojson <your_file.geojson> --output-dir <output_dir>"
