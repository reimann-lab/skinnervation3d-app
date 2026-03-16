# SkInnervation3D – User Interface

This application is a desktop tool that provides a user interface to define image-analysis workflows without writing code. The workflows are defined using Fractal task packages for image pre-processing (whole sample processing: conversion to OME-Zarr, illumination correction, stitching, etc.) and downstream skin innervation analysis (fiber segmentation, counting, surface fitting, etc.).

The graphical interface allows to:  
- choose an analysis folder  
- select an image dataset  
- configure analysis steps  
- run them in order  
- monitor progress and logs  

---

## Installation

This application is intended for authorized users and has currently some of its dependencies that are being distributed privately.
To be able to complete the installation, you need either a wheel or zip file of the dependencies or a Personal Access Token PAT. See the [installation guide](docs/installation.md) for more information on how to generate a PAT.

This section describes how to install the application either using the installer script or manually.

### Automatic Installation

The provided installer scripts will download all dependencies and install the application automatically. It is the recommended way to install the application. It supports macOS, Linux, and Windows. You can find more information about the automatic installation in the [installation guide](docs/installation.md).

### Windows
Download the latest release of the [Windows Installer](https://github.com/reimann-lab/skinnervation3d-app/releases/latest/download/windows_installer.zip), unzip it and run the installer by double-clicking on the file `install.bat` inside the folder.


### macOS / Linux
Download these two files into the same folder, then run `bash install.sh` in a terminal:
Download the latest release of the [Linux/MacOS Installer](https://github.com/reimann-lab/skinnervation3d-app/releases/latest/download/linux_mac_installer.zip), unzip it and run the installer by double-clicking on the file `install.sh` inside the folder for MacOS or run `bash install.sh` in a terminal for Linux.

---

### Manual Installation

#### Requirements

- Python: >= 3.11 and < 3.13  
- Operating system: macOS, Linux, Windows  
- Recommended environment manager:  
	- conda or mamba (via Miniforge)  
	- pyenv also works for advanced users  

⚠️ Using a virtual environment is strongly recommended.

#### Procedure

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

    Install the SkInnervation3D app and the dependencies in the Conda/Mamba environment. The easiest way is to download a wheel file from the [releases page](https://github.com/reimann-lab/skinnervation3d-app/releases) and install it with pip:

    ```
    pip install skinnervation3d_app-*.whl
    pip install skinnervation3d_fractal_tasks-*.whl
    pip install mesospim_fractal_tasks-*.whl
    ```

4. Install the Napari dependency (for visualisation)

    It is recommended to install Napari and the Napari Crop plugin in a separate environment for better isolation. The plugin has not yet been published to the Napari Hub, thus you need to download a wheel file from the [releases page](https://github.com/girochat/napari-crop-tool/releases) and install it with pip:

    ```
    mamba env create -f environment_napari.yml
    mamba activate napari-crop
    pip install napari_crop_tool-*.whl
    ```
---

## License

This project is licensed under the **BSD 3-Clause License** — see [LICENSE](LICENSE) for details.

---
