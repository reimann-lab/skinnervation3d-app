# SkInnervation3D – User Interface

This application is a desktop tool that provides a user interface to define image-analysis workflows without writing code. The workflows are defined using Fractal task packages for image pre-processing (whole sample processing: conversion to OME-Zarr, illumination correction, stitching, etc.) and downstream skin innervation analysis (fiber segmentation, counting, surface fitting, etc.).

The graphical interface allows to:  
- choose an analysis folder  
- select an image dataset  
- configure analysis steps  
- run them in order  
- monitor progress and logs  

## Installation

This application is intended for authorized users and is currently distributed privately.
Some dependencies are not publicly available and must be provided separately (wheel or source archive).

### Requirements

- Python: >= 3.11 and < 3.13  
- Operating system: macOS, Linux, Windows  
- Recommended environment manager:  
	- conda or mamba (via Miniforge)  
	- pyenv also works for advanced users  

⚠️ Using a virtual environment is strongly recommended.

### Procedure

#### With Conda/Mamba

1. Install Miniforge

    If not already installed, download Miniforge from: https://github.com/conda-forge/miniforge

    Make sure conda or mamba is available in your shell.

2. Create a Conda or Mamba environment

    An environment.yml file is provided to ensure all dependencies are installed with compatible versions. First, run in the terminal:

    ```
    mamba env create -f environment.yml  
    mamba activate skin3d-app
    ```

3. Install Dependencies

    Install the SkInnervation3D app and the dependencies in the Conda/Mamba environment:

    ```
    pip install skinnervation3d_app-*.whl
    pip install skinnervation3d_fractal_tasks-*.whl
    pip install mesospim_fractal_tasks-*.whl
    ```

4. Install the Napari dependency (for visualisation)

    It is recommended to install Napari in a separate environment for better isolation.

    ```
    mamba env create -f environment_napari.yml
    mamba activate napari-crop
    pip install napari-crop-tool-*.whl
    ```

