# Forklift Front Camera System

## Overview

The **Forklift Front Camera System** is an industrial edge application for real-time pallet QR detection, operator confirmation, and cloud synchronization.  
It is designed for forklift-mounted devices and supports controlled **Storage** and **Dispatch** workflows through a simple Human-Machine Interface (HMI).

The system integrates camera-based QR detection with manual validation to ensure reliable pallet movement tracking in warehouse and brewery environments.

## Key Features

- Real-time QR code detection
- Stable detection to prevent duplicate scans
- Operator confirmation via HMI
- Storage and Dispatch workflow support
- Cloud API and WebSocket integration
- Industrial camera support (V4L2-based)
- Logging and basic error handling

## Supported Platforms

- Ubuntu 20.04+
- Industrial edge devices
- Advantech iCAM-540 or compatible cameras
- Python 3.8+

## Installation

Clone the repository:

```bash
git clone https://github.com/<your-org>/forklift-front-end.git
cd forklift-front-end
````

Create and activate a virtual environment: (optional)

```bash
python3 -m venv venv
source venv/bin/activate
```

(Windows: `venv\Scripts\activate`)

Install system dependencies (Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y libzbar0
```

Install Python dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Running the Application

Start the system:

```bash
python3 main.py
```

This launches the camera, QR detection pipeline, operator HMI, and cloud synchronization.

## Version

* Version: 1.0.0
* Last Updated: January 2026

## License

Proprietary – All rights reserved.

